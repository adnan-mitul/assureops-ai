"""Lease renewal after takeover, cancellation versus finalization, single finalization."""

from sqlalchemy import select, text

from assureops_api import services as svc
from assureops_domain.db import tenant_session
from assureops_domain.models import Assessment, JobStep, ReadinessPoint
from assureops_domain.profile import profile_version
from assureops_worker.tasks import _maybe_finalize, claim, renew_lease
from tests.conftest import add_release, prof


def _job(ws, tests=("T-C01-01", "T-C02-01")):
    release = add_release(ws, "R1")
    with tenant_session(ws) as s:
        job = Assessment(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, scope="full", plan_id="p", plan={"tests": list(tests)},
                         profile_version=profile_version(prof()), edge_revision="e", requested_by="t")
        s.add(job)
        s.flush()
        ids = []
        for i, t in enumerate(tests):
            step = JobStep(workspace_id=ws, assessment_id=job.id, step_key=f"{job.id}:{t}", test_id=t, position=i)
            s.add(step)
            s.flush()
            ids.append(step.id)
        return job.id, ids


def test_lease_renewal_stops_after_takeover(workspace):
    _, (step_id, _) = _job(workspace)
    first = claim(workspace, step_id)
    assert renew_lease(workspace, step_id, first)
    with tenant_session(workspace) as s:
        s.execute(text("UPDATE job_steps SET lease_expires_at = 0 WHERE id = :id"), {"id": step_id})
    second = claim(workspace, step_id)
    assert second == first + 1
    assert not renew_lease(workspace, step_id, first)  # the stale runner is told to stop
    assert renew_lease(workspace, step_id, second)


def test_cancellation_marks_pending_steps_and_finalizes_once(workspace):
    job_id, (running_id, pending_id) = _job(workspace)
    claim(workspace, running_id)
    with tenant_session(workspace) as s:
        svc.cancel_assessment(s, s.get(Assessment, job_id))
    with tenant_session(workspace) as s:
        assert s.get(JobStep, pending_id).status == "cancelled"
        _maybe_finalize(s, job_id)
        assert s.get(Assessment, job_id).status == "running" or s.get(Assessment, job_id).status == "queued"  # a step still runs
    with tenant_session(workspace) as s:
        s.execute(text("UPDATE job_steps SET status = 'done' WHERE id = :id"), {"id": running_id})
    for _ in range(2):  # concurrent finishers both call finalize; the row lock and status check keep it single
        with tenant_session(workspace) as s:
            _maybe_finalize(s, job_id)
    with tenant_session(workspace) as s:
        assert s.get(Assessment, job_id).status == "cancelled"
        assert len(s.scalars(select(ReadinessPoint).where(ReadinessPoint.assessment_id == job_id)).all()) == 1


def test_reconciler_redispatches_an_orphaned_step_at_most_once_per_window(workspace):
    from assureops_domain.db import platform_session
    from assureops_domain.models import Outbox
    from assureops_worker.dispatcher import reconcile_once

    _, (step_id, _) = _job(workspace)
    claim(workspace, step_id)
    with tenant_session(workspace) as s:  # the worker died: lease expired, last touched just now
        s.execute(text("UPDATE job_steps SET lease_expires_at = 0, updated_at = extract(epoch from now()) WHERE id = :id"), {"id": step_id})

    def intents():
        with platform_session() as p:
            return len(p.scalars(select(Outbox).where(Outbox.ref_id == step_id)).all())

    before = intents()
    reconcile_once()
    assert intents() == before  # inside the back-off window: no new dispatch
    with tenant_session(workspace) as s:
        s.execute(text("UPDATE job_steps SET updated_at = 0 WHERE id = :id"), {"id": step_id})
    reconcile_once()
    reconcile_once()
    assert intents() == before + 1  # exactly one re-dispatch, then back-off again
