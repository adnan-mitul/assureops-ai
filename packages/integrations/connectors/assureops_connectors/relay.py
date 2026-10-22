"""AssureOps private connector (relay): run inside the customer network, connect outbound only.

    python -m assureops_connectors.relay --api https://assureops.example.com --token-file /run/secrets/assureops-relay
    python -m assureops_connectors.relay --api ... --token-file ... --once     # one claim, then exit (cron or CI)

The relay holds one application-bound relay credential and no other AssureOps secret. Each
claimed task runs in a fresh `python -I -m assureops_connectors.sandbox` process with a scrubbed
environment, exactly like the hosted runner: one frozen test or one connection check, requests
pinned to the connection's origin, redirects refused. The capsule exists only in memory and on the
sandbox's stdin. Results go back with the claim nonce; nothing is cached on disk.
"""

import argparse
import json
import os
import subprocess
import sys
import time

import httpx

SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL")


def scrubbed_env() -> dict:
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", NO_PROXY="*")
    return env


def run_sandbox(payload: dict, timeout: float) -> dict:
    try:
        proc = subprocess.run([sys.executable, "-I", "-m", "assureops_connectors.sandbox"], input=json.dumps(payload).encode(),
                              capture_output=True, timeout=max(timeout, 1), env=scrubbed_env())
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": f"relay sandbox exceeded {int(timeout)} s", "trials": []}
    try:
        return json.loads(proc.stdout or b"{}")
    except json.JSONDecodeError:
        return {"status": "error", "error": "relay sandbox returned no result", "trials": []}


class Relay:
    def __init__(self, api: str, token: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=api.rstrip("/"), timeout=30, follow_redirects=False)
        self.client.headers["Authorization"] = f"Bearer {token}"

    def once(self) -> str:
        """Claim and run at most one task. Returns idle | done | refused."""
        res = self.client.post("/v1/integration/relay/claim")
        if res.status_code == 204:
            return "idle"
        res.raise_for_status()
        task = res.json()
        result = run_sandbox(task["payload"], task["deadline_at"] - time.time() - 2)
        task["payload"] = None  # drop the capsule (and its credentials) before reporting
        back = self.client.post(f"/v1/integration/relay/tasks/{task['task_id']}/result", json={"nonce": task["nonce"], "result": result})
        return "done" if back.status_code == 200 else "refused"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    with open(args.token_file, encoding="utf-8") as f:
        token = f.read().strip()
    relay = Relay(args.api, token)
    while True:
        try:
            outcome = relay.once()
        except httpx.HTTPError as exc:
            outcome = f"error: {exc.__class__.__name__}"
        print(f"relay: {outcome}", flush=True)
        if args.once:
            return 0
        if outcome != "done":
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
