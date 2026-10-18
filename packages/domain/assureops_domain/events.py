"""Runtime event ingestion and classification (plan §12).

Classification rules come from the application's profile (`runtime.rules`),
evaluated as data. A blocked attempt is never a violation; only rules that a
profile marks as tool-side verified (`classification: violation`) open
incidents. Unknown events stay `observed`.
"""

import json
import re

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import matchers
from .findings import open_runtime_violation
from .models import Assessment, Connection, EventSource, JobStep, RuntimeEvent, now
from .profile import canonical_hash, try_for_application

RUN_TOKEN = re.compile(r"\bao-[0-9a-f]{12}\b")
WINDOW_SKEW = 3.0

REQUIRED = ("event_id", "source_id", "epoch", "seq", "release", "event_type", "observed_at")
MAX_BATCH = 100
FUTURE_SKEW_SECONDS = 120


def _resolve(value, p: dict):
    """`$requirements.x` references the profile's numeric requirements; anything else is literal."""
    if isinstance(value, str) and value.startswith("$requirements."):
        return p["requirements"][value.split(".", 1)[1]]
    return value


def match_rule(source: EventSource, event: dict, p: dict | None) -> dict | None:
    for rule in ((p or {}).get("runtime") or {}).get("rules", []):
        if rule.get("source_kinds") and source.kind not in rule["source_kinds"]:
            continue
        if rule.get("event_type") and rule["event_type"] != event["event_type"]:
            continue
        conditions = [{**c, "value": _resolve(c.get("value"), p)} for c in rule.get("all", [])]
        if matchers.evaluate(event, conditions):
            return rule
    return None


def attribute(session: Session, source: EventSource, event: dict) -> str | None:
    """Recognise AssureOps' own assessment traffic. Strong: an HMAC run token issued to a step of this application.
    Weak: a declared synthetic test identity acting inside a step's execution window. Anything else is live."""
    blob = json.dumps(event.get("payload", {}), sort_keys=True)
    for token in set(RUN_TOKEN.findall(blob)):
        hit = session.execute(text("SELECT 1 FROM job_steps j JOIN assessments a ON a.id = j.assessment_id AND a.workspace_id = j.workspace_id "
                                   "WHERE a.application_id = :app AND j.run_tokens::jsonb ? :t LIMIT 1"),
                              {"t": token, "app": source.application_id}).first()
        if hit:
            return "run_token"
    conn = session.scalars(select(Connection).where(Connection.application_id == source.application_id, Connection.status != "superseded")
                           .order_by(Connection.revision.desc())).first()
    identities = set(((conn.config.get("actor_identities") or {}) if conn else {}).values())
    actor = (event.get("payload") or {}).get("actor")
    if actor and actor in identities:
        t = event["observed_at"]
        window = session.scalars(select(JobStep).join(Assessment, (Assessment.id == JobStep.assessment_id) & (Assessment.workspace_id == JobStep.workspace_id))
                                 .where(Assessment.application_id == source.application_id,
                                        JobStep.started_at.is_not(None), JobStep.started_at <= t + WINDOW_SKEW,
                                                       (JobStep.finished_at.is_(None)) | (JobStep.finished_at >= t - WINDOW_SKEW))).first()
        if window is not None:
            return "test_identity_in_assessment_window"
    return None


def classify(source: EventSource, event: dict, p: dict | None = None) -> tuple[str, dict | None]:
    payload = event.get("payload", {})
    if event["event_type"] == "heartbeat":
        return "heartbeat", None
    if event.get("test_traffic"):
        return "assessment_traffic", None
    if payload.get("outcome") == "blocked":
        return "enforcement_blocked", None  # supports blocking tests; never a control failure by itself
    rule = match_rule(source, event, p)
    if rule:
        classification = rule["classification"]
        if classification == "violation" and source.kind not in (rule.get("verified_by") or ["tool_server", "application"]):
            classification = "review_required"  # only a tool-side/system-of-record source can verify an effect
        return classification, rule
    return "observed", None


def ingest(session: Session, source: EventSource, events: list[dict]) -> list[dict]:
    results = []
    p = try_for_application(session, source.application_id)
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
        attribution = attribute(session, source, event) if not event.get("test_traffic") else "declared_by_source"
        if attribution:
            event = {**event, "test_traffic": True}
            flags["test_attribution"] = attribution
        classification, rule = classify(source, event, p)
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
            observed = [f"{name}={value}" for name, value in (("amount_minor", matchers.lookup(event, "payload.amount_minor")),
                                                             ("action_id", matchers.lookup(event, "payload.action_id")))
                        if value is not matchers.MISSING]
            open_runtime_violation(session, workspace_id=source.workspace_id, application_id=source.application_id, control_id=rule["control"],
                                   release=event["release"], event_revision=row.revision, severity=rule.get("severity", "critical"),
                                   title=rule.get("title", "Verified unauthorized effect in operation"),
                                   description=(f"{source.kind} {source.id} reported {event['event_type']} on release {event['release']} "
                                                f"matching rule {rule['id']}. {rule.get('explanation', '')} "
                                                f"Observed: {', '.join(observed) or 'see event'}.").strip())
        results.append({"event_id": event["event_id"], "status": "accepted", "classification": classification, "revision": row.revision, **flags})
    return results


def coverage(session: Session, contract: dict, window_seconds: int = 60, expected_release: str | None = None) -> dict:
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
        cohort_mismatch = bool(expected_release and last.release not in (expected_release, "unknown"))
        if now() - last.received_at > window_seconds:
            status = "unknown"
        else:
            status = "degraded" if missing or cohort_mismatch else "current"
        sources.append({"source_id": sid, "kind": expected["kind"], "status": status, "last_seen": last.received_at,
                        "release": last.release, "expected_release": expected_release, "cohort_mismatch": cohort_mismatch,
                        "epoch": last.epoch, "missing_sequences": missing})
    current = sum(s["status"] == "current" for s in sources)
    overall = "not_connected" if sources and all(s["status"] == "not_connected" for s in sources) else (
        "current" if sources and current == len(sources) else "degraded" if current else "unknown")
    return {"status": overall, "current": current, "expected": len(sources), "sources": sources}
