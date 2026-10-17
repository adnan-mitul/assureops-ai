"""Durable step execution (plan §11).

PostgreSQL is the source of truth; Celery/Redis only schedules. A worker claims
a step with a lease and a new fencing token, and its result commits only if the
token and revision are still current, so a stale worker cannot overwrite a
newer owner. Each logical step has at most one committed result.
"""

import os
import socket
import time

from celery import Celery
from sqlalchemy import select, text

from assureops_domain import evidence_store, reducer
from assureops_domain.config import settings
from assureops_domain.db import tenant_session
from assureops_domain.findings import record_test_outcome
from assureops_domain.models import Application, Assessment, AssessmentCase, JobStep, ReadinessPoint, Release, TestRun, now
from assureops_domain.profile import canonical_hash, profile, profile_version
from assureops_domain import cases

from . import runner

app = Celery("assureops", broker=settings().redis_url)
app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, task_default_queue="assessments")

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_SECONDS = 120


class StaleOwner(Exception):
    pass


def claim(workspace_id: str, step_id: str) -> int | None:
    """Claim using database time; returns the fencing token or None if not claimable."""
    with tenant_session(workspace_id) as s:
        row = s.execute(text("""
            UPDATE job_steps SET status = 'running', attempt = attempt + 1, lease_owner = :owner,
                   lease_expires_at = extract(epoch from now()) + :lease, fencing_token = fencing_token + 1,
                   updated_at = extract(epoch from now())
            WHERE id = :id AND attempt < max_attempts
              AND (status = 'pending' OR (status = 'running' AND lease_expires_at < extract(epoch from now())))
            RETURNING fencing_token"""), {"owner": WORKER_ID, "lease": LEASE_SECONDS, "id": step_id}).first()
        return row[0] if row else None


@app.task(name="assureops.run_step", bind=True, max_retries=0)
def run_step(self, workspace_id: str, step_id: str):
    with tenant_session(workspace_id) as s:
        step = s.get(JobStep, step_id)
        if step is None or step.status in ("done", "cancelled"):
            return "skipped"  # duplicate delivery of an already finished step
        job = s.get(Assessment, step.assessment_id)
        if job.cancel_requested:
            step.status = "cancelled"
            s.flush()
            _maybe_finalize(s, job)
            return "cancelled"
    token = claim(workspace_id, step_id)
    if token is None:
        return "not_claimable"
    with tenant_session(workspace_id) as s:
        s.execute(text("UPDATE assessments SET status = 'running' WHERE id = :id AND status = 'queued'"), {"id": step.assessment_id})

    with tenant_session(workspace_id) as s:
        step = s.get(JobStep, step_id)
        job = s.get(Assessment, step.assessment_id)
        app_row = s.get(Application, job.application_id)
        release = s.get(Release, job.release_id)
        edges = reducer.accepted_edges(s, app_row.id)
        s.expunge_all()

    test = profile()["tests_by_id"][step.test_id]
    target = runner.Target(app_row, release, step_id)
    trials, error = [], None
    try:
        live = target.manifest()
        if canonical_hash(live["components"]) != release.manifest_hash:
            # Evidence from a different running release must never be attributed to this one.
            raise RuntimeError(f"target is running {live['release']} with different components, not assessed release {release.version}")
        for _ in range(test["trials"]):
            ok, record = runner.IMPLEMENTATIONS[step.test_id](target)
            trials.append({"passed": bool(ok), "record": record})
    except Exception as exc:  # infrastructure or identity error: not proof of an application defect
        error = f"{exc.__class__.__name__}: {exc}"

    with tenant_session(workspace_id) as s:
        current = s.scalars(select(JobStep).where(JobStep.id == step_id).with_for_update()).first()
        if current.fencing_token != token or current.status != "running":
            raise StaleOwner(f"step {step_id} was taken over; result discarded")
        if error and current.attempt < current.max_attempts and "not assessed release" not in error:
            current.status, current.last_error, current.lease_owner = "pending", error, None
            from assureops_domain.models import Outbox
            s.add(Outbox(workspace_id=workspace_id, kind="run_step", ref_id=step_id))
            return "retry_scheduled"
        passed = sum(t["passed"] for t in trials)
        outcome = "error" if error else ("passed" if passed == len(trials) else "failed")
        record = {"test_id": step.test_id, "release": release.version, "expected": runner.EXPECTED[step.test_id], "error": error,
                  "trials": trials, "worker": WORKER_ID, "fencing_token": token, "attempt": current.attempt}
        artifact = evidence_store.put_json(s, workspace_id, record)
        run = TestRun(workspace_id=workspace_id, application_id=app_row.id, release_id=release.id, assessment_id=job.id, step_id=step_id,
                      test_id=step.test_id, control_id=test["control"], outcome=outcome, trials=len(trials) or test["trials"], passed_trials=passed,
                      trial_outcomes=[t["passed"] for t in trials], dependency_fingerprints=reducer.dependency_fingerprints(release, edges.get(step.test_id, [])),
                      profile_version=profile_version(), artifact_id=artifact.id, expected=runner.EXPECTED[step.test_id],
                      observation_source="AssureOps runner via agent HTTP and tool-side MCP status")
        s.add(run)
        s.flush()
        current.status, current.result_run_id, current.last_error, current.updated_at = ("failed" if error else "done"), run.id, error, now()
        record_test_outcome(s, run, release)
        s.flush()
        _maybe_finalize(s, s.get(Assessment, job.id))
    return outcome


def _maybe_finalize(s, job: Assessment):
    """Transactional finalization once every step has a terminal state."""
    steps = s.scalars(select(JobStep).where(JobStep.assessment_id == job.id)).all()
    if any(st.status in ("pending", "running") for st in steps) or job.status in ("completed", "failed", "cancelled"):
        return
    release = s.get(Release, job.release_id)
    state = reducer.readiness(s, job.application_id, release)
    errors = [st.test_id for st in steps if st.status == "failed"]
    if job.cancel_requested:
        job.status = "cancelled"
    elif errors and all("not assessed release" in (st.last_error or "") for st in steps if st.status == "failed"):
        job.status, job.error = "failed", "target release identity did not match; no evidence attributed"
    else:
        job.status = "awaiting_review" if state["gate"]["incomplete"] and any(t["result"] == "review_required" for t in state["tests"]) else "completed"
        if errors:
            job.error = f"infrastructure errors on {', '.join(errors)}"
    job.finished_at = now()
    job.summary = {"results": [{"test_id": st.test_id, "status": st.status, "run_id": st.result_run_id} for st in steps],
                   "gate": state["gate"]["status"], "scores": state["scores"]}
    s.add(ReadinessPoint(workspace_id=job.workspace_id, application_id=job.application_id, assessment_id=job.id, release=release.version,
                         evidence_support=state["scores"]["evidence_support_pct"] or 0, evidence_coverage=state["scores"]["evidence_coverage_pct"] or 0))
    if job.case_id:
        case = s.get(AssessmentCase, job.case_id)
        cases.sync_index(s, case, blockers=len(state["gate"]["blocking"]))


@app.task(name="assureops.finalize_assessment")
def finalize_assessment(workspace_id: str, assessment_id: str):
    with tenant_session(workspace_id) as s:
        _maybe_finalize(s, s.get(Assessment, assessment_id))
