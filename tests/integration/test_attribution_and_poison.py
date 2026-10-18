"""Assessment-traffic attribution, incident grouping and poison-step completion."""

import time
import uuid

from sqlalchemy import select, text

from assureops_domain import events
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Assessment, EventSource, Incident, JobStep
from assureops_domain.profile import profile_version
from assureops_worker.tasks import fail_poison
from tests.conftest import add_release, prof


def _source(ws):
    src = EventSource(id=f"{ws}-tools", workspace_id=ws, application_id=f"{ws}-app", environment="staging", kind="tool_server",
                      token_hash=uuid.uuid4().hex)
    with platform_session() as s:
        s.add(src)
    return src


def _event(src, seq, action_id):
    return {"event_id": uuid.uuid4().hex, "source_id": src.id, "epoch": "e1", "seq": seq, "release": "R2", "event_type": "refund_committed",
            "observed_at": time.time(), "payload": {"amount_minor": 250000, "approval_id": None, "action_id": action_id}}


def _job(ws, release, tokens, status="done", attempt=1, max_attempts=3):
    with tenant_session(ws) as s:
        job = Assessment(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, scope="full", plan_id="p", plan={},
                         profile_version=profile_version(prof()), edge_revision="e", requested_by="t", status="running")
        s.add(job)
        s.flush()
        step = JobStep(workspace_id=ws, assessment_id=job.id, step_key=f"{job.id}:T-C03-01", test_id="T-C03-01", position=0, status=status,
                       run_tokens=tokens, attempt=attempt, max_attempts=max_attempts, started_at=time.time() - 5, finished_at=time.time())
        s.add(step)
        s.flush()
        return job.id, step.id


def test_platform_run_token_marks_assessment_traffic_and_unknown_token_does_not(workspace):
    release = add_release(workspace, "R2")
    _job(workspace, release, ["ao-0123456789ab"])
    src = _source(workspace)
    with tenant_session(workspace) as s:
        ours, foreign = events.ingest(s, src, [_event(src, 1, "ao-0123456789ab-missing"), _event(src, 2, "ao-ffffffffffff-missing")])
    assert ours["classification"] == "assessment_traffic" and ours["test_attribution"] == "run_token"
    assert foreign["classification"] == "violation"  # a token the platform never issued proves nothing


def test_violations_for_one_control_and_cohort_group_into_one_incident(workspace):
    add_release(workspace, "R2")
    src = _source(workspace)
    with tenant_session(workspace) as s:
        events.ingest(s, src, [_event(src, 1, "live-1"), _event(src, 2, "live-2")])
    with tenant_session(workspace) as s:
        incidents = s.scalars(select(Incident)).all()
    assert len(incidents) == 1 and len(incidents[0].event_revisions) == 2


def test_poison_step_reaches_terminal_state_and_finalizes(workspace):
    release = add_release(workspace, "R1")
    job_id, step_id = _job(workspace, release, [], status="pending", attempt=3, max_attempts=3)
    with tenant_session(workspace) as s:
        s.execute(text("UPDATE job_steps SET finished_at = NULL WHERE id = :id"), {"id": step_id})
    assert fail_poison(workspace, step_id)
    with tenant_session(workspace) as s:
        step = s.get(JobStep, step_id)
        job = s.get(Assessment, job_id)
        assert step.status == "failed" and "poison" in step.last_error
        assert job.status in ("completed", "awaiting_review") and job.finished_at is not None
