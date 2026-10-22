"""Private connector (relay): customer-run, outbound-only execution for targets the hosted service cannot reach.

A connection opts in with `execution: {"mode": "relay"}`. The worker then queues each step's
capsule as a relay task instead of starting a local runner, keeps renewing its own lease, and
waits for the result. The relay (assureops_connectors.relay) runs inside the customer network,
claims one task with its application-bound credential, executes it in the same scrubbed sandbox
the hosted runner uses, and posts the result with the claim nonce.

Guarantees:
- payloads are encrypted at rest and readable once: a claim wipes the ciphertext;
- a relay credential sees only tasks of its own application;
- a result needs the claim nonce, arrives once, and is refused after the deadline;
- a missed deadline is an error (retry or unverified), never a pass;
- the step's fencing token still decides whether a late result may be recorded.
"""

import hashlib
import json
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import vault
from .db import tenant_session
from .models import RelayTask, now

CLAIM_POLL_SECONDS = 2.0


class RelayError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def is_relay(config: dict | None) -> bool:
    return ((config or {}).get("execution") or {}).get("mode") == "relay"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def enqueue(s: Session, *, workspace_id: str, application_id: str, kind: str, ref_id: str, payload: dict, deadline_seconds: float,
            fencing_token: int | None = None) -> RelayTask:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    task = RelayTask(workspace_id=workspace_id, application_id=application_id, kind=kind, ref_id=ref_id, fencing_token=fencing_token,
                     payload_ciphertext=vault._fernet().encrypt(raw.encode()).decode(), payload_sha256=_hash(raw),
                     deadline_at=now() + deadline_seconds)
    s.add(task)
    s.flush()
    return task


def expire_overdue(s: Session, application_id: str) -> int:
    n = 0
    for t in s.scalars(select(RelayTask).where(RelayTask.application_id == application_id, RelayTask.status.in_(["queued", "claimed"]),
                                               RelayTask.deadline_at < now())):
        t.status, t.payload_ciphertext, t.error = "expired", None, "relay did not finish before the deadline"
        n += 1
    return n


def claim(s: Session, *, application_id: str, credential_id: str) -> dict | None:
    """Hand the oldest queued task of this application to one relay, exactly once."""
    expire_overdue(s, application_id)
    task = s.scalars(select(RelayTask).where(RelayTask.application_id == application_id, RelayTask.status == "queued")
                     .order_by(RelayTask.created_at).limit(1).with_for_update(skip_locked=True)).first()
    if task is None:
        return None
    payload = json.loads(vault._fernet().decrypt(task.payload_ciphertext.encode()))
    nonce = "rln_" + secrets.token_urlsafe(24)
    task.status, task.claim_nonce_hash, task.claimed_by, task.claimed_at = "claimed", _hash(nonce), credential_id, now()
    task.payload_ciphertext = None  # one-time: the decrypted capsule exists only in this response and in the relay's memory
    return {"task_id": task.id, "kind": task.kind, "nonce": nonce, "deadline_at": task.deadline_at, "payload": payload,
            "payload_sha256": task.payload_sha256}


def complete(s: Session, *, task_id: str, application_id: str, credential_id: str, nonce: str, result: dict) -> RelayTask:
    task = s.scalars(select(RelayTask).where(RelayTask.id == task_id).with_for_update()).first()
    if task is None or task.application_id != application_id:
        raise RelayError("not_found", "relay task not found")
    if task.status != "claimed":
        raise RelayError("not_claimed", f"task is {task.status}; a result is accepted once, for a claimed task")
    if task.claimed_by != credential_id or task.claim_nonce_hash != _hash(nonce):
        raise RelayError("bad_nonce", "result does not match the claim")
    if task.deadline_at < now():
        task.status, task.error = "expired", "result arrived after the deadline"
        raise RelayError("expired", "the deadline passed; the result was not recorded")
    if not isinstance(result, dict) or len(json.dumps(result)) > 4_000_000:
        raise RelayError("invalid_result", "result must be a JSON object under 4 MB")
    task.status, task.result, task.completed_at = "completed", result, now()
    return task


def wait_for_result(workspace_id: str, task_id: str, *, timeout: float, on_tick=None) -> dict:
    """Worker side: poll the task row, renewing the step lease through `on_tick`; returns the sandbox-style result."""
    started, last_tick = time.time(), time.time()
    while True:
        with tenant_session(workspace_id) as s:
            task = s.get(RelayTask, task_id)
            if task.status == "completed":
                return task.result
            if task.status in ("expired", "cancelled") or task.deadline_at < now():
                if task.status in ("queued", "claimed"):
                    task.status, task.payload_ciphertext, task.error = "expired", None, "relay did not finish before the deadline"
                return {"status": "error", "error": f"relay_timeout: no relay result within {int(timeout)} s ({task.status})", "trials": []}
        if on_tick and time.time() - last_tick >= 10:
            on_tick()
            last_tick = time.time()
        if time.time() - started > timeout + 5:
            return {"status": "error", "error": "relay_timeout: worker deadline", "trials": []}
        time.sleep(CLAIM_POLL_SECONDS)


def to_json(t: RelayTask) -> dict:
    return {"id": t.id, "kind": t.kind, "ref_id": t.ref_id, "status": t.status, "created_at": t.created_at, "deadline_at": t.deadline_at,
            "claimed_at": t.claimed_at, "completed_at": t.completed_at, "error": t.error, "payload_sha256": t.payload_sha256[:16]}
