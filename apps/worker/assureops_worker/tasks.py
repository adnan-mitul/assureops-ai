"""Durable step execution (plan §11, integration plan I1).

PostgreSQL is the source of truth; Celery/Redis only schedules. A worker claims
a step with a lease and a new fencing token, renews the lease while the
isolated runner works, and commits only if the token is still current, so a
stale worker cannot overwrite a newer owner. Each logical step has at most one
committed result. Tests, release, profile, connection and evaluator revisions
come from the assessment's frozen plan, never from whatever is current.
"""

import os
import socket

from celery import Celery
from sqlalchemy import select, text

from assureops_domain import cases, connections, evidence_store, reducer, relay
from assureops_domain.config import settings
from assureops_domain.db import tenant_session
from assureops_domain.findings import record_test_outcome
from assureops_domain.models import Application, Assessment, AssessmentCase, Connection, JobStep, Outbox, ReadinessPoint, Release, TestRun, now
from assureops_domain.profile import canonical_hash, for_application, profile_version

from . import isolation, runner

app = Celery("assureops", broker=settings().redis_url)
app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, task_default_queue="assessments",
                # Model work has its own queue and worker with concurrency 1: one active inference request per instance.
                task_routes={"assureops.ai_phase": {"queue": "ai"}, "assureops.source_analysis": {"queue": "analysis"}})

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_SECONDS = 120
STEP_DEADLINE_PER_TRIAL = 90
NO_RETRY_MARKERS = ("identity_mismatch", "InvalidTest", "credential", "EgressDenied")


class StaleOwner(Exception):
    pass


def claim(workspace_id: str, step_id: str) -> int | None:
    """Claim using database time; returns the fencing token or None if not claimable."""
    with tenant_session(workspace_id) as s:
        row = s.execute(text("""
            UPDATE job_steps SET status = 'running', attempt = attempt + 1, lease_owner = :owner,
                   lease_expires_at = extract(epoch from now()) + :lease, fencing_token = fencing_token + 1,
                   started_at = extract(epoch from now()), updated_at = extract(epoch from now())
            WHERE id = :id AND attempt < max_attempts
              AND (status = 'pending' OR (status = 'running' AND lease_expires_at < extract(epoch from now())))
            RETURNING fencing_token"""), {"owner": WORKER_ID, "lease": LEASE_SECONDS, "id": step_id}).first()
        return row[0] if row else None


def renew_lease(workspace_id: str, step_id: str, token: int) -> bool:
    with tenant_session(workspace_id) as s:
        row = s.execute(text("""
            UPDATE job_steps SET lease_expires_at = extract(epoch from now()) + :lease, updated_at = extract(epoch from now())
            WHERE id = :id AND fencing_token = :token AND status = 'running' RETURNING id"""),
            {"lease": LEASE_SECONDS, "id": step_id, "token": token}).first()
        return row is not None


def fail_poison(workspace_id: str, step_id: str) -> bool:
    """A step out of attempts gets a terminal state so its assessment can finish truthfully."""
    with tenant_session(workspace_id) as s:
        step = s.scalars(select(JobStep).where(JobStep.id == step_id).with_for_update()).first()
        if step is None or step.status not in ("pending", "running") or step.attempt < step.max_attempts:
            return False
        if step.status == "running" and (step.lease_expires_at or 0) > now():
            return False
        step.status, step.last_error, step.finished_at = "failed", (step.last_error or "") + " | poison: attempts exhausted", now()
        s.flush()
        _maybe_finalize(s, step.assessment_id)
        return True


def _frozen_target(job: Assessment, app_row: Application, conn: Connection | None, p: dict) -> runner.FrozenTarget:
    rel = job.frozen["release"]
    config = conn.config if conn else {}
    return runner.FrozenTarget(workspace_id=job.workspace_id, application_id=app_row.id, environment=job.frozen.get("environment", app_row.environment),
                               base_url=config.get("base_url", app_row.target_url), tools_url=config.get("tools_url", app_row.tools_url),
                               release_version=rel["version"], manifest=rel["manifest"],
                               self_approval_allowed=bool(p["requirements"].get("self_approval_allowed")))


def _run_reference(job, app_row, conn, p, test, step_id) -> dict:
    """In-process path for the bundled MCP reference agent only."""
    target = runner.Target(_frozen_target(job, app_row, conn, p), step_id)
    live = target.manifest()
    if canonical_hash(live["components"]) != job.frozen["release"]["manifest_hash"] or live["release"] != job.frozen["release"]["version"]:
        return {"status": "error", "error": f"identity_mismatch: target is running {live['release']} with different components, "
                                            f"not assessed release {job.frozen['release']['version']}", "trials": []}
    trials = []
    try:
        for _ in range(test["trials"]):
            ok, record = runner.IMPLEMENTATIONS[test["args"]["implementation"]](target)
            trials.append(runner.trial(ok, record))
    except Exception as exc:  # infrastructure error: not proof of an application defect
        return {"status": "error", "error": f"{exc.__class__.__name__}: {exc}", "trials": trials}
    return {"status": "completed", "trials": trials, "adapter": "assureops-mcp-reference", "adapter_version": "0.3.0",
            "evaluator_version": "reference-runner-1.1.0"}  # 1.1: "inconclusive" when the attempt is never made


def _run_via_relay(workspace_id: str, application_id: str, step_id: str, token: int, capsule: dict, timeout: float, tick) -> dict:
    """Queue the capsule for the customer's relay and wait; the step keeps its lease and fencing token meanwhile."""
    with tenant_session(workspace_id) as s:
        task = relay.enqueue(s, workspace_id=workspace_id, application_id=application_id, kind="step", ref_id=step_id, payload=capsule,
                             deadline_seconds=timeout, fencing_token=token)
        task_id = task.id
    return relay.wait_for_result(workspace_id, task_id, timeout=timeout, on_tick=tick)


@app.task(name="assureops.run_step", bind=True, max_retries=0)
def run_step(self, workspace_id: str, step_id: str):
    with tenant_session(workspace_id) as s:
        step = s.get(JobStep, step_id)
        if step is None or step.status in ("done", "cancelled", "failed"):
            return "skipped"  # duplicate delivery of an already finished step
        job = s.get(Assessment, step.assessment_id)
        if job.cancel_requested:
            step.status, step.finished_at = "cancelled", now()
            s.flush()
            _maybe_finalize(s, job.id)
            return "cancelled"
    token = claim(workspace_id, step_id)
    if token is None:
        return "poisoned" if fail_poison(workspace_id, step_id) else "not_claimable"

    with tenant_session(workspace_id) as s:
        s.execute(text("UPDATE assessments SET status = 'running' WHERE id = :id AND status = 'queued'"), {"id": step.assessment_id})
        step = s.get(JobStep, step_id)
        job = s.get(Assessment, step.assessment_id)
        app_row = s.get(Application, job.application_id)
        frozen = job.frozen
        p = for_application(s, app_row.id, revision=frozen["profile"]["revision"])
        test = frozen["tests"][step.test_id]
        conn = s.scalars(select(Connection).where(Connection.application_id == app_row.id,
                                                  Connection.revision == frozen["connection"]["revision"])).first() if frozen.get("connection") else None
        tokens = connections.run_tokens(f"{step_id}:{step.attempt}", test["trials"])
        step.run_tokens = [*(step.run_tokens or []), *tokens]
        attempt = step.attempt
        capsule = None
        if frozen["connection"]["adapter_id"] != "assureops-mcp-reference":
            spec, problems = connections.spec_for(s, conn, with_credentials=True) if conn else (None, ["connection missing"])
            if problems or conn.status == "revoked":
                capsule = {"__error__": "credential unavailable: " + "; ".join(problems or ["connection revoked"])}
            else:
                capsule = {"adapter_id": conn.adapter_id, "connection_revision": conn.revision, "config": conn.config,
                           "credentials": spec.credentials, "allow_private": spec.allow_private, "step_id": step_id,
                           "release_version": frozen["release"]["version"], "frozen_manifest": frozen["release"]["manifest"],
                           "manifest_hash": frozen["release"]["manifest_hash"], "run_tokens": tokens, "test": test,
                           "identity_check": True}
        s.expunge_all()

    def tick():
        if not renew_lease(workspace_id, step_id, token):
            raise StaleOwner(f"lease for {step_id} was lost")

    try:
        if capsule is None:
            outcome_raw = _run_reference(job, app_row, conn, p, test, step_id)
        elif "__error__" in capsule:
            outcome_raw = {"status": "error", "error": capsule["__error__"], "trials": []}
        elif relay.is_relay(capsule["config"]):
            outcome_raw = _run_via_relay(workspace_id, app_row.id, step_id, token, capsule, STEP_DEADLINE_PER_TRIAL * test["trials"], tick)
        else:
            outcome_raw = isolation.run_capsule(capsule, timeout=STEP_DEADLINE_PER_TRIAL * test["trials"], on_tick=tick)
        capsule = None  # drop decrypted credentials as soon as the runner returns
    except StaleOwner:
        return "stale_owner"
    except isolation.RunnerFailure as exc:
        outcome_raw = {"status": "error", "error": f"RunnerFailure: {exc}", "trials": []}

    error = outcome_raw.get("error") if outcome_raw.get("status") != "completed" else None
    trials = outcome_raw.get("trials", [])
    with tenant_session(workspace_id) as s:
        current = s.scalars(select(JobStep).where(JobStep.id == step_id).with_for_update()).first()
        if current.fencing_token != token or current.status != "running":
            raise StaleOwner(f"step {step_id} was taken over; result discarded")
        if error and current.attempt < current.max_attempts and not any(m in error for m in NO_RETRY_MARKERS):
            current.status, current.last_error, current.lease_owner = "pending", error, None
            s.add(Outbox(workspace_id=workspace_id, kind="run_step", ref_id=step_id))
            return "retry_scheduled"
        job = s.get(Assessment, current.assessment_id)
        release = s.get(Release, job.release_id)
        passed = sum(t["passed"] for t in trials)
        unexercised = sum(bool(t.get("inconclusive")) for t in trials)
        # Inconclusive only when no trial failed: one real failure is a failure whatever the other trials did.
        outcome = "error" if error else ("passed" if passed == len(trials) else "failed" if len(trials) - passed - unexercised
                                         else "inconclusive")
        record = {"test_id": current.test_id, "template": test.get("template"), "release": release.version,
                  "release_manifest_hash": release.manifest_hash, "expected": test["expected"], "error": error,
                  "partial_record": outcome_raw.get("partial_record"), "trials": trials,
                  "frozen": {"profile": frozen["profile"], "connection": frozen.get("connection"), "test_digest": test["digest"],
                             "evaluator": outcome_raw.get("evaluator_version") or frozen["connection"].get("evaluator_version")},
                  "execution": {"mode": "in-process reference runner" if frozen["connection"]["adapter_id"] == "assureops-mcp-reference"
                                else "customer relay (private connector)" if frozen["connection"].get("execution_mode") == "relay"
                                else f"isolated {settings().runner_mode}", "worker": WORKER_ID, "fencing_token": token, "attempt": attempt,
                                "run_tokens": current.run_tokens}}
        artifact = evidence_store.put_json(s, workspace_id, record)
        edges = reducer.accepted_edges(s, job.application_id, p)
        run = TestRun(workspace_id=workspace_id, application_id=job.application_id, release_id=release.id, assessment_id=job.id, step_id=step_id,
                      test_id=current.test_id, control_id=test["control"], outcome=outcome, trials=len(trials) or test["trials"], passed_trials=passed,
                      trial_outcomes=[None if t.get("inconclusive") else t["passed"] for t in trials], dependency_fingerprints=reducer.dependency_fingerprints(release, edges.get(current.test_id, [])),
                      profile_version=profile_version(p), artifact_id=artifact.id, expected=test["expected"],
                      observation_source=_observation_source(frozen), test_digest=test["digest"],
                      evaluator_version=outcome_raw.get("evaluator_version") or frozen["connection"].get("evaluator_version", ""))
        s.add(run)
        s.flush()
        current.status, current.result_run_id, current.last_error = ("failed" if error else "done"), run.id, error
        current.updated_at = current.finished_at = now()
        record_test_outcome(s, run, release, p)
        s.flush()
        _maybe_finalize(s, job.id)
    return outcome


def _observation_source(frozen: dict) -> str:
    if frozen["connection"]["adapter_id"] == "assureops-mcp-reference":
        return "AssureOps reference runner via agent HTTP and tool-side MCP status"
    return f"AssureOps isolated runner via {frozen['connection']['adapter_id']} (connection r{frozen['connection']['revision']})"


def _maybe_finalize(s, assessment_id: str):
    """Transactional finalization once every step is terminal; the row lock serializes concurrent finishers."""
    job = s.scalars(select(Assessment).where(Assessment.id == assessment_id).with_for_update()).first()
    if job is None or job.status in ("completed", "failed", "cancelled"):
        return
    steps = s.scalars(select(JobStep).where(JobStep.assessment_id == job.id)).all()
    if any(st.status in ("pending", "running") for st in steps):
        return
    release = s.get(Release, job.release_id)
    p = for_application(s, job.application_id)
    state = reducer.readiness(s, job.application_id, release, p)
    errors = [st.test_id for st in steps if st.status == "failed"]
    if job.cancel_requested:
        job.status = "cancelled"
    elif errors and all("identity_mismatch" in (st.last_error or "") for st in steps if st.status == "failed") and len(errors) == len(steps):
        job.status, job.error = "failed", "target release identity did not match; no evidence attributed"
    else:
        job.status = "awaiting_review" if any(t["result"] == "review_required" for t in state["tests"]) else "completed"
        if errors:
            job.error = f"unverified (infrastructure or precondition) on {', '.join(errors)}"
    job.finished_at = now()
    job.summary = {"results": [{"test_id": st.test_id, "status": st.status, "run_id": st.result_run_id} for st in steps],
                   "gate": state["gate"]["status"], "scores": state["scores"], "profile": state["profile"]["version"]}
    s.add(ReadinessPoint(workspace_id=job.workspace_id, application_id=job.application_id, assessment_id=job.id, release=release.version,
                         evidence_support=state["scores"]["evidence_support_pct"] or 0, evidence_coverage=state["scores"]["evidence_coverage_pct"] or 0))
    if job.case_id:
        case = s.get(AssessmentCase, job.case_id)
        cases.sync_index(s, case, blockers=len(state["gate"]["blocking"]))
    from assureops_domain import notices

    sc = state["scores"]
    notices.change(s, s.get(Application, job.application_id), subject=f"Assessment of {release.version} {job.status.replace('_', ' ')}",
                   body=(f"Assessment {job.id} ({job.scope}, requested by {job.requested_by}) finished as {job.status.replace('_', ' ')}. "
                         f"Gate: {state['gate']['status']}. Evidence support {sc['evidence_support_pct']}%, coverage {sc['evidence_coverage_pct']}%. "
                         f"{state['gate']['reason']}"))


@app.task(name="assureops.finalize_assessment")
def finalize_assessment(workspace_id: str, assessment_id: str):
    with tenant_session(workspace_id) as s:
        _maybe_finalize(s, assessment_id)


@app.task(name="assureops.ai_phase")
def ai_phase(workspace_id: str, result_id: str):
    """Model-assisted phase job; proposals only, validated before persistence."""
    from assureops_ai import service

    return service.execute(workspace_id, result_id)


@app.task(name="assureops.source_analysis")
def source_analysis(workspace_id: str, run_id: str):
    """Analyze an authorized snapshot (pinned REA when installed, otherwise the built-in collector) and link it to the release."""
    from assureops_rea import analyzer

    from assureops_domain.models import AnalysisRun, Artifact

    with tenant_session(workspace_id) as s:
        run = s.scalars(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()).first()
        if run is None or run.status not in ("pending", "running"):
            return "skipped"
        run.status = "running"
        data = evidence_store.read_bytes(s.get(Artifact, run.snapshot_artifact_id))
        manifest = s.get(Release, run.release_id).manifest
        code_map = dict(run.code_map or {})
    try:
        files = analyzer.read_snapshot(data)
        result = analyzer.builtin(files)
        rea = analyzer.rea_status()
        if rea["available"]:
            import tempfile
            from pathlib import Path as _Path

            with tempfile.TemporaryDirectory(prefix="ao-rea-") as tmp:  # extracted copy for REA; never executed
                for rel, content in files.items():
                    target = _Path(tmp, *rel.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                try:
                    rea_result = analyzer.run_rea(_Path(tmp))
                    result["rea"] = rea_result
                    result["analyzer"] = f"{result['analyzer']} + {rea_result['analyzer']}"
                    result["observations"] += rea_result["observations"]
                    result["gaps"] += rea_result["gaps"]
                except analyzer.AnalysisError as exc:
                    result["gaps"].append(f"REA run failed: {exc}")
        else:
            result["gaps"].append(f"REA {rea['reason']}; built-in collector used")
        comparison = analyzer.compare_with_manifest(result, manifest, code_map)
        status, error = "completed", None
    except analyzer.AnalysisError as exc:
        result, comparison, status, error = None, None, "quarantined" if "schema" in str(exc) else "failed", str(exc)
    with tenant_session(workspace_id) as s:
        run = s.get(AnalysisRun, run_id)
        if result is not None:
            artifact = evidence_store.put_json(s, workspace_id, {"analysis": result, "comparison": comparison, "snapshot_sha256": run.snapshot_sha256})
            run.result_artifact_id = artifact.id
            run.analyzer = result["analyzer"]
            run.summary = {**comparison, "coverage": result["coverage"], "gaps": result["gaps"],
                           "observations": len(result["observations"]), "result_sha256": artifact.sha256,
                           "rea": {k: result["rea"][k] for k in ("analyzer", "evidence_id", "subject_sha256", "coverage")} if result.get("rea") else None}
        run.status, run.error, run.finished_at = status, error, now()
    return status
