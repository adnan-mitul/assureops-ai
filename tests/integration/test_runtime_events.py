"""T14: event trust, ordering and the blocked-attempt versus violation distinction."""

import time
import uuid

from sqlalchemy import select

from assureops_domain import events
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import EventSource, Finding, Incident


def source(ws: str, kind: str) -> EventSource:
    src = EventSource(id=f"{ws}-{kind}", workspace_id=ws, application_id=f"{ws}-app", environment="staging", kind=kind, token_hash=uuid.uuid4().hex)
    with platform_session() as s:
        s.add(src)
    return src


def event(src: EventSource, seq: int, event_type: str, payload: dict, **extra) -> dict:
    return {"event_id": uuid.uuid4().hex, "source_id": src.id, "epoch": "e1", "seq": seq, "release": "R2", "event_type": event_type,
            "observed_at": time.time(), "payload": payload, **extra}


def ingest(ws, src, batch):
    with tenant_session(ws) as s:
        return events.ingest(s, src, batch)


def test_blocked_attempt_is_not_a_violation(workspace):
    agent = source(workspace, "agent")
    [result] = ingest(workspace, agent, [event(agent, 1, "tool_call", {"tool": "issue_refund", "outcome": "blocked", "reason": "approval_required"})])
    assert result["classification"] == "enforcement_blocked"
    with tenant_session(workspace) as s:
        assert s.scalars(select(Incident)).all() == []


def test_tool_side_unapproved_commit_opens_incident_and_finding(workspace):
    tools = source(workspace, "tool_server")
    [result] = ingest(workspace, tools, [event(tools, 1, "refund_committed", {"amount_minor": 250000, "approval_id": None, "action_id": "a1"})])
    assert result["classification"] == "violation"
    with tenant_session(workspace) as s:
        incident = s.scalars(select(Incident)).one()
        assert incident.cohort == "R2" and incident.state == "open"
        assert s.get(Finding, incident.finding_id).source == "runtime"


def test_assessment_traffic_never_opens_incidents(workspace):
    tools = source(workspace, "tool_server")
    [result] = ingest(workspace, tools, [event(tools, 1, "refund_committed", {"amount_minor": 250000, "approval_id": None}, test_traffic=True)])
    assert result["classification"] == "assessment_traffic"


def test_agent_only_claim_needs_review(workspace):
    agent = source(workspace, "agent")
    [result] = ingest(workspace, agent, [event(agent, 1, "tool_call", {"tool": "issue_refund", "outcome": "executed", "approval_id": None})])
    assert result["classification"] == "review_required"


def test_duplicates_are_idempotent_and_conflicts_quarantined(workspace):
    agent = source(workspace, "agent")
    e = event(agent, 1, "heartbeat", {})
    assert ingest(workspace, agent, [e])[0]["status"] == "accepted"
    assert ingest(workspace, agent, [e])[0]["status"] == "duplicate"
    assert ingest(workspace, agent, [{**e, "payload": {"changed": True}}])[0]["status"] == "conflict_quarantined"


def test_environment_mismatch_rejected_and_gaps_flagged(workspace):
    agent = source(workspace, "agent")
    assert ingest(workspace, agent, [event(agent, 1, "heartbeat", {}, environment="production")])[0]["status"] == "rejected"
    ingest(workspace, agent, [event(agent, 1, "heartbeat", {})])
    assert ingest(workspace, agent, [event(agent, 3, "heartbeat", {})])[0]["sequence_gap"] is True
    contract = {"runtime_sources": [{"source_id": agent.id, "kind": "agent"}]}
    with tenant_session(workspace) as s:
        cov = events.coverage(s, contract)
    assert cov["sources"][0]["missing_sequences"] == 1 and cov["status"] != "current"
