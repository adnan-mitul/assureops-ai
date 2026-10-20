"""Runtime event bridge: pull an application's own event log, add AssureOps source identity, deliver durably.

    python -m assureops_connectors.bridge --api http://127.0.0.1:8700 --source-id refunddesk-bridge-1 \
        --source-token-file var/bridge/refunddesk-bridge-1.token --connection profiles/connections/refunddesk-demo.json \
        --actors-file var/demo-actors/refunddesk-demo.json [--once]

Runs beside the customer's application (inside their network). Every event is
written to a local SQLite spool before delivery and removed from the queue only
after the platform acknowledges it, so restarts and outages lose nothing. The
bridge owns a contiguous sequence per epoch; when the upstream log skipped
records (for example history truncated before the bridge saw them), the bridge
skips the same number of sequence numbers so the platform reports a gap instead
of silently assuming completeness. Heartbeats prove liveness.
"""

import argparse
import json
import sqlite3
import time
import uuid
from pathlib import Path

import httpx

from assureops_domain import matchers

from .base import ConnectionSpec, get

BATCH = 100


class Spool:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS queue (seq INTEGER NOT NULL, epoch TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (epoch, seq))")
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT v FROM state WHERE k = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute("INSERT INTO state VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, json.dumps(value)))

    def enqueue(self, epoch: str, seq: int, body: dict):
        self.db.execute("INSERT OR IGNORE INTO queue VALUES (?, ?, ?)", (seq, epoch, json.dumps(body)))

    def pending(self, limit=BATCH) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM queue ORDER BY epoch, seq LIMIT ?", (limit,))]

    def ack(self, event_ids: set[str]):
        for body in self.pending(10_000):
            if body["event_id"] in event_ids:
                self.db.execute("DELETE FROM queue WHERE epoch = ? AND seq = ?", (body["epoch"], body["seq"]))
        self.db.commit()


class Bridge:
    def __init__(self, *, api: str, source_id: str, token: str, connection: dict, credentials: dict, spool: Path, allow_private: bool = True):
        self.api = api.rstrip("/")
        self.source_id = source_id
        self.token = token
        config = {k: v for k, v in connection["config"].items() if v is not None}
        self.spec = ConnectionSpec(adapter_id=connection["adapter_id"], revision=0, config=config, credentials=credentials,
                                   allow_private=allow_private)
        self.adapter = get(self.spec.adapter_id)
        self.events_cfg = config["events"]
        self.spool = Spool(spool)
        if self.spool.get("epoch") is None:
            self._new_epoch()
            self.spool.db.commit()

    def _new_epoch(self):
        self.spool.put("epoch", uuid.uuid4().hex[:10])
        self.spool.put("next_seq", 1)
        self.spool.put("last_upstream", 0)

    def _next(self, skip: int = 0) -> int:
        seq = self.spool.get("next_seq") + skip
        self.spool.put("next_seq", seq + 1)
        return seq

    def collect(self) -> int:
        """Read new upstream records and spool them as normalized events. Returns how many were spooled."""
        client = self.adapter.client(self.spec)
        try:
            res = client.request("GET", self.events_cfg["path"], actor=self.events_cfg.get("actor"), enforce_scope=False)
        finally:
            client.close()
        rows = matchers.lookup(res["body"], self.events_cfg.get("list_path", "events")) if res["status"] == 200 else matchers.MISSING
        if not isinstance(rows, list):
            raise RuntimeError(f"event endpoint answered HTTP {res['status']}")
        rows = sorted(rows, key=lambda r: r.get("sequence", 0))
        last = self.spool.get("last_upstream")
        if rows and rows[-1].get("sequence", 0) < last:  # upstream log was reset: start a new epoch, never merge histories
            self._new_epoch()
            last = 0
        count = 0
        for raw in rows:
            up = int(raw.get("sequence", 0))
            if up <= last:
                continue
            missed = max(up - last - 1, 0) if last else 0
            epoch = self.spool.get("epoch")
            event = self.adapter.normalize_event(self.spec, raw, source_id=self.source_id, epoch=epoch)
            event["seq"] = self._next(skip=missed)  # skipped numbers surface as a gap on the platform
            event["environment"] = self.spec.config.get("environment", "staging")
            event["payload"]["upstream_sequence"] = up
            self.spool.enqueue(epoch, event["seq"], event)
            last = up
            count += 1
        self.spool.put("last_upstream", last)
        self.spool.db.commit()
        return count

    def heartbeat(self, release: str = "unknown"):
        epoch = self.spool.get("epoch")
        seq = self._next()
        self.spool.enqueue(epoch, seq, {"event_id": f"{self.source_id}:{epoch}:hb:{seq}", "source_id": self.source_id, "epoch": epoch,
                                        "seq": seq, "release": release, "event_type": "heartbeat", "observed_at": time.time(),
                                        "environment": self.spec.config.get("environment", "staging"),
                                        "payload": {"spooled": len(self.spool.pending(10_000))}})
        self.spool.db.commit()

    def deliver(self) -> dict:
        sent = accepted = 0
        while True:
            batch = self.spool.pending()
            if not batch:
                break
            try:
                res = httpx.post(f"{self.api}/v1/runtime/events:batch", json={"events": batch},
                                 headers={"Authorization": f"Bearer {self.token}"}, timeout=10, trust_env=False)
            except httpx.HTTPError as exc:
                return {"sent": sent, "accepted": accepted, "error": f"platform unreachable: {exc.__class__.__name__}"}
            if res.status_code != 200:
                return {"sent": sent, "accepted": accepted, "error": f"platform answered HTTP {res.status_code}"}
            results = res.json()["results"]
            done = {r["event_id"] for r in results if r["status"] in ("accepted", "duplicate")}
            rejected = [r for r in results if r["status"] not in ("accepted", "duplicate")]
            self.spool.ack(done | {r["event_id"] for r in rejected})  # rejections are final; keep them out of the retry loop
            sent += len(batch)
            accepted += len(done)
            if rejected:
                print(f"rejected by platform: {[(r['event_id'], r.get('reason') or r['status']) for r in rejected][:5]}")
        return {"sent": sent, "accepted": accepted}

    def current_release(self) -> str:
        try:
            return self.adapter.collect_manifest(self.spec)["manifest"]["release"]
        except Exception:
            return "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-token-file", required=True)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--actors-file", required=True)
    parser.add_argument("--spool", default=None)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--heartbeat", type=float, default=20.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    bridge = Bridge(api=args.api, source_id=args.source_id, token=Path(args.source_token_file).read_text(encoding="utf-8").strip(),
                    connection=json.loads(Path(args.connection).read_text(encoding="utf-8")),
                    credentials=json.loads(Path(args.actors_file).read_text(encoding="utf-8")),
                    spool=Path(args.spool or f"var/bridge/{args.source_id}.sqlite3"))
    last_hb = 0.0
    while True:
        try:
            spooled = bridge.collect()
        except Exception as exc:  # keep running; nothing is lost from the spool
            spooled, _ = 0, print(f"collect failed: {exc.__class__.__name__}: {exc}")
        if time.time() - last_hb >= args.heartbeat:
            bridge.heartbeat(bridge.current_release())
            last_hb = time.time()
        result = bridge.deliver()
        if spooled or result.get("error"):
            print(f"spooled {spooled}, delivery {result}", flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
