"""T13: a stale worker cannot commit after another worker took over the lease."""

from sqlalchemy import text

from assureops_domain.db import tenant_session
from assureops_domain.models import Assessment, JobStep
from assureops_domain.profile import profile_version
from assureops_worker.tasks import claim
from tests.conftest import add_release


def test_fencing_token_increases_and_lease_takeover_is_detected(workspace):
    release = add_release(workspace, "R1")
    with tenant_session(workspace) as s:
        job = Assessment(workspace_id=workspace, application_id=f"{workspace}-app", release_id=release.id, scope="full", plan_id="p",
                         plan={"tests": ["T-C01-01"]}, profile_version=profile_version(), edge_revision="e", requested_by="test")
        s.add(job)
        s.flush()
        step = JobStep(workspace_id=workspace, assessment_id=job.id, step_key=f"{job.id}:T-C01-01", test_id="T-C01-01", position=0)
        s.add(step)
        s.flush()
        step_id = step.id

    first = claim(workspace, step_id)
    assert first == 1
    assert claim(workspace, step_id) is None  # lease still held

    with tenant_session(workspace) as s:  # simulate lease expiry while the first worker is still running
        s.execute(text("UPDATE job_steps SET lease_expires_at = 0 WHERE id = :id"), {"id": step_id})
    second = claim(workspace, step_id)
    assert second == 2

    with tenant_session(workspace) as s:
        current = s.get(JobStep, step_id)
        assert current.fencing_token != first  # the stale worker's commit check fails
