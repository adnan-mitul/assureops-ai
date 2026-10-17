"""Runtime event ingestion and classification (plan §12)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .findings import open_runtime_violation
from .models import EventSource, RuntimeEvent, now
from .profile import canonical_hash, profile

REQUIRED = ("event_id", "source_id", "epoch", "seq", "release", "event_type", "observed_at")
MAX_BATCH = 100
FUTURE_SKEW_SECONDS = 120


def classify(source: EventSource, event: dict) -> str:
    payload = event.get("payload", {})
    if event["event_type"] == "heartbeat":
        return "heartbeat"
    if event.get("test_traffic"):
        return "assessment_traffic"
    if payload.get("outcome") == "blocked":
        return "enforcement_blocked"  # supports blocking tests; never a control failure by itself
    if source.kind == "tool_server" and event["event_type"] == "refund_committed":
        threshold = profile()["requirements"]["consequential_write_approval_above_minor"]
        if payload.get("amount_minor", 0) > threshold and not payload.get("approval_id"):
            return "violation"  # verified by the tool-side record
        return "observed"
    if source.kind == "agent" and payload.get("tool") == "issue_refund" and payload.get("outcome") == "executed" and not payload.get("approval_id"):
        return "review_required"  # agent claim only; corroboration comes from the tool server
    return "observed"


def ingest(session: Session, source: EventSource, events: list[dict]) -> list[dict]:
    results = []
    for event in events[:MAX_BATCH]:
        missing = [k for k in REQUIRED if k not in event]
        if missing:
            results.append({"event_id": event.get("event_id"), "status": "rejected", "reason": f"missing {missing}"})
            continue
        if event["source_id"] != source.id:
            results.append({"event_id": event["event_id"], "status": "rejected", "reason": "source identity mismatch"})
            continue
        if event.get("environment", source.environment) != source.environment:
            results.append({"event_id": event["event_id"], "status": "rejected", "reason": "credential cannot report another environment"})
            continue
        body_hash = canonical_hash(event)
        existing = session.scalars(select(RuntimeEvent).where(RuntimeEvent.event_id == event["event_id"])).first()
        if existing:
            status = "duplicate" if existing.body_hash == body_hash else "conflict_quarantined"
            results.append({"event_id": event["event_id"], "status": status})
            continue
        last_seq = session.scalar(select(func.max(RuntimeEvent.seq)).where(RuntimeEvent.source_id == source.id, RuntimeEvent.epoch == event["epoch"]))
        flags = {
            "sequence_gap": bool(last_seq and event["seq"] > last_seq + 1),
            "out_of_order": bool(last_seq and event["seq"] < last_seq),
            "future_timestamp": event["observed_at"] > now() + FUTURE_SKEW_SECONDS,
        }
        classification = classify(source, event)
        row = RuntimeEvent(
            workspace_id=source.workspace_id, event_id=event["event_id"], application_id=source.application_id,
            environment=source.environment, source_id=source.id, epoch=event["epoch"], seq=event["seq"], release=event["release"],
            event_type=event["event_type"], classification=classification, trust_origin=f"authenticated {source.kind} credential",
            action_id=event.get("payload", {}).get("action_id"), payload={**event.get("payload", {}), **flags}, body_hash=body_hash,
            observed_at=event["observed_at"],
        )
        session.add(row)
        session.flush()  # persisted before acknowledgement
        if classification == "violation":
            open_runtime_violation(session, workspace_id=source.workspace_id, application_id=source.application_id, control_id="C03",
                                   release=event["release"], event_revision=row.revision,
                                   description=(f"Tool server {source.id} committed a refund of {event['payload'].get('amount_minor', 0) / 100:.2f} "
                                                f"on release {event['release']} with no approval; the profile requires approval above "
                                                f"{profile()['requirements']['consequential_write_approval_above_minor'] / 100:.2f}."))
        results.append({"event_id": event["event_id"], "status": "accepted", "classification": classification, "revision": row.revision, **flags})
    return results


def coverage(session: Session, contract: dict, window_seconds: int = 60) -> dict:
    """Coverage per expected source; missing heartbeats or gaps are never read as healthy."""
    sources = []
    for expected in contract.get("runtime_sources", []):
        sid = expected["source_id"]
        last = session.scalars(select(RuntimeEvent).where(RuntimeEvent.source_id == sid).order_by(RuntimeEvent.revision.desc())).first()
        if last is None:
            sources.append({"source_id": sid, "kind": expected["kind"], "status": "not_connected", "last_seen": None, "release": None, "missing_sequences": 0})
            continue
        seqs = set(session.scalars(select(RuntimeEvent.seq).where(RuntimeEvent.source_id == sid, RuntimeEvent.epoch == last.epoch)))
        missing = max(seqs) - min(seqs) + 1 - len(seqs)
        if now() - last.received_at > window_seconds:
            status = "unknown"
        else:
            status = "degraded" if missing else "current"
        sources.append({"source_id": sid, "kind": expected["kind"], "status": status, "last_seen": last.received_at,
                        "release": last.release, "epoch": last.epoch, "missing_sequences": missing})
    current = sum(s["status"] == "current" for s in sources)
    overall = "not_connected" if sources and all(s["status"] == "not_connected" for s in sources) else (
        "current" if sources and current == len(sources) else "degraded" if current else "unknown")
    return {"status": overall, "current": current, "expected": len(sources), "sources": sources}
