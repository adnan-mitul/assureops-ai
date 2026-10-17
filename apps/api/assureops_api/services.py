"""Shared domain operations used by both portals' routes and the integration surface.

Callers authorize first and pass a tenant-scoped session; nothing here reads
another workspace's rows.
"""

import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from assureops_domain import evidence_store, reducer
from assureops_domain.events import coverage
from assureops_domain.models import (
    Application, Artifact, Assessment, AssessmentCase, CaseMessage, ChangeSet, CoverageContract, EvidenceRequest, EvidenceReview,
    Finding, FindingReview, Incident, JobStep, Outbox, ReadinessPoint, Release, Report, ReportPublication, RuntimeEvent, TestRun,
)
from assureops_domain.profile import canonical_hash, profile, profile_version

from .auth import api_error

MANIFEST_REQUIRED = {"schema_version", "application", "release", "components", "collection"}


def ts(value):
    return round(value, 3) if value else value


def get_application(s: Session, application_id: str) -> Application:
    app = s.get(Application, application_id)
    if app is None:
        raise api_error(404, "not_found", "application not found")  # also hides other workspaces' IDs
    return app


def latest_release(s: Session, application_id: str) -> Release | None:
    return s.scalars(select(Release).where(Release.application_id == application_id).order_by(Release.created_at.desc())).first()


def previous_release(s: Session, release: Release) -> Release | None:
    return s.scalars(select(Release).where(Release.application_id == release.application_id, Release.created_at < release.created_at)
                     .order_by(Release.created_at.desc())).first()


def contract(s: Session, application_id: str) -> dict:
    row = s.scalars(select(CoverageContract).where(CoverageContract.application_id == application_id).order_by(CoverageContract.revision.desc())).first()
    return {**row.contract, "revision": row.revision, "reviewer": row.reviewer} if row else {}


def release_json(r: Release) -> dict:
    return {"id": r.id, "version": r.version, "manifest_hash": r.manifest_hash[:12], "manifest_hash_full": r.manifest_hash, "components": r.manifest["components"],
            "policy_versions": r.manifest.get("policy_versions", {}), "integration": r.manifest.get("integration", {}),
            "collection_status": r.collection_status, "collection_gaps": r.collection_gaps, "created_at": ts(r.created_at)}


# ---------------- Releases ----------------

def collect_release(s: Session, app: Application, actor: str) -> dict:
    """Validate the target's manifest and record it as an immutable release; return collection gaps."""
    try:
        manifest = httpx.get(f"{app.target_url}/manifest", timeout=10).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise api_error(502, "target_unreachable", f"could not collect the manifest: {exc.__class__.__name__}")
    missing = MANIFEST_REQUIRED - set(manifest)
    if missing or not isinstance(manifest.get("components"), dict):
        raise api_error(422, "invalid_manifest", f"manifest rejected: missing {sorted(missing)}")
    gaps = list(manifest["collection"].get("gaps", []))
    mandatory = {c for comps in contract(s, app.id).get("mandatory_components", {}).values() for c in comps}
    gaps += [f"mandatory component not collected: {c}" for c in sorted(mandatory - set(manifest["components"]))]
    manifest_hash = canonical_hash(manifest["components"])
    existing = s.scalars(select(Release).where(Release.application_id == app.id, Release.manifest_hash == manifest_hash)).first()
    if existing:
        return {"release": release_json(existing), "created": False, "gaps": existing.collection_gaps}
    release = Release(workspace_id=app.workspace_id, application_id=app.id, version=manifest["release"], manifest=manifest,
                      manifest_hash=manifest_hash, collection_gaps=gaps, collection_status="partial" if gaps else "complete", collected_by=actor)
    s.add(release)
    s.flush()
    return {"release": release_json(release), "created": True, "gaps": gaps}


# ---------------- Assessments ----------------

def create_assessment(s: Session, app: Application, release: Release, scope: str, actor: str, *, case_id: str | None = None,
                      idempotency_key: str | None = None, plan_override: list[str] | None = None) -> Assessment:
    request_hash = canonical_hash({"release": release.id, "scope": scope, "plan": plan_override})
    if idempotency_key:
        existing = s.scalars(select(Assessment).where(Assessment.idempotency_key == idempotency_key)).first()
        if existing:
            if existing.request_hash != request_hash:
                raise api_error(409, "idempotency_conflict", "this idempotency key was used with a different request")
            return existing
    if s.scalars(select(Assessment).where(Assessment.application_id == app.id, Assessment.status.in_(["queued", "running"]))).first():
        raise api_error(409, "assessment_running", "an assessment is already running for this application")
    state = reducer.readiness(s, app.id, release)
    tests = plan_override if plan_override is not None else reducer.retest_plan(state, scope)
    edges = reducer.accepted_edges(s, app.id)
    plan_id = canonical_hash({"release": release.id, "tests": tests, "profile": profile_version(), "edges": reducer.edge_revision(edges)})[:16]
    job = Assessment(workspace_id=app.workspace_id, application_id=app.id, release_id=release.id, case_id=case_id, scope=scope, plan_id=plan_id,
                     plan={"tests": tests}, profile_version=profile_version(), edge_revision=reducer.edge_revision(edges),
                     idempotency_key=idempotency_key, request_hash=request_hash, requested_by=actor)
    s.add(job)
    s.flush()
    tests_by_id = profile()["tests_by_id"]
    for position, test_id in enumerate(tests):
        step = JobStep(workspace_id=app.workspace_id, assessment_id=job.id, step_key=f"{job.id}:{test_id}", test_id=test_id,
                       position=position, max_attempts=3 if tests_by_id[test_id]["trials"] else 3)
        s.add(step)
        s.flush()
        # Outbox row commits in the same transaction as the domain transition.
        s.add(Outbox(workspace_id=app.workspace_id, kind="run_step", ref_id=step.id))
    if not tests:
        s.add(Outbox(workspace_id=app.workspace_id, kind="finalize_assessment", ref_id=job.id))
    return job


def assessment_json(a: Assessment, s: Session) -> dict:
    steps = s.scalars(select(JobStep).where(JobStep.assessment_id == a.id).order_by(JobStep.position)).all()
    outcomes = {r.id: r.outcome for r in s.scalars(select(TestRun).where(TestRun.assessment_id == a.id))}
    release = s.get(Release, a.release_id)
    return {
        "id": a.id, "application_id": a.application_id, "release": release.version if release else None, "scope": a.scope, "status": a.status, "plan_id": a.plan_id,
        "profile_version": a.profile_version, "tests": a.plan.get("tests", []), "case_id": a.case_id, "requested_by": a.requested_by,
        "steps": [{"test_id": st.test_id, "status": st.status, "attempt": st.attempt, "error": st.last_error, "run_id": st.result_run_id,
                   "outcome": outcomes.get(st.result_run_id)} for st in steps],
        "summary": a.summary, "error": a.error, "cancel_requested": a.cancel_requested,
        "created_at": ts(a.created_at), "finished_at": ts(a.finished_at),
    }


# ---------------- Changes ----------------

def create_change_set(s: Session, app: Application, target: Release, base: Release | None, actor: str) -> ChangeSet:
    result = reducer.compare(s, app.id, base, target)
    state = reducer.readiness(s, app.id, target)
    plan = reducer.retest_plan(state, "retest")
    plan_id = canonical_hash({"target": target.id, "base": base.id if base else None, "plan": plan, "edges": result["edge_revision"]})[:16]
    result["plan"] = plan
    change = ChangeSet(workspace_id=app.workspace_id, application_id=app.id, base_release_id=base.id if base else None,
                       target_release_id=target.id, result=result, plan_id=plan_id, created_by=actor)
    s.add(change)
    s.flush()
    return change


def change_json(c: ChangeSet) -> dict:
    return {"id": c.id, "plan_id": c.plan_id, "created_at": ts(c.created_at), "created_by": c.created_by, **c.result}


# ---------------- Findings and evidence ----------------

def finding_json(f: Finding, s: Session, detail: bool = False) -> dict:
    data = {"id": f.id, "control": f.control_id, "control_name": profile()["controls"][f.control_id]["name"], "test_id": f.test_id,
            "source": f.source, "severity": f.severity, "title": f.title, "description": f.description, "state": f.state,
            "revision": f.revision, "first_release": f.first_release, "last_release": f.last_release, "evidence_refs": f.evidence_refs,
            "resolution": f.resolution, "remediation_note": f.remediation_note, "created_at": ts(f.created_at), "updated_at": ts(f.updated_at)}
    if detail:
        data["reviews"] = [{"reviewer": r.reviewer, "reviewer_kind": r.reviewer_kind, "decision": r.decision, "note": r.note,
                            "at": ts(r.created_at)} for r in s.scalars(select(FindingReview).where(FindingReview.finding_id == f.id).order_by(FindingReview.created_at))]
    return data


def evidence_json(run: TestRun, s: Session, with_record: bool = False) -> dict:
    artifact = s.get(Artifact, run.artifact_id)
    release = s.get(Release, run.release_id)
    review = s.scalars(select(EvidenceReview).where(EvidenceReview.run_id == run.id).order_by(EvidenceReview.created_at.desc())).first()
    test = profile()["tests_by_id"][run.test_id]
    data = {
        "id": run.id, "test_id": run.test_id, "test_name": test["name"], "control": run.control_id,
        "control_name": profile()["controls"][run.control_id]["name"], "claim": test["name"], "release": release.version,
        "outcome": run.outcome, "trials": run.trials, "passed_trials": run.passed_trials, "trial_outcomes": run.trial_outcomes,
        "expected": run.expected, "observation_source": run.observation_source, "origin": "tested",
        "collection_scope": f"{release.version} · staging · profile {run.profile_version}",
        "dependency_fingerprints": run.dependency_fingerprints, "evidence_hash": artifact.sha256 if artifact else None,
        "available": evidence_store.available(artifact), "model_role": "none — deterministic test and rules",
        "review": {"reviewer": review.reviewer, "decision": review.decision, "note": review.note, "at": ts(review.created_at)} if review else None,
        "created_at": ts(run.created_at),
    }
    if with_record:
        try:
            data["record"] = evidence_store.read_json(artifact)
        except evidence_store.EvidenceUnavailable as exc:
            data["record"], data["unavailable_reason"] = None, str(exc)
    return data


# ---------------- Monitoring and health ----------------

def probe_health(app: Application) -> dict:
    """Operational health of the assessed application, measured separately from assessment coverage."""
    started = time.perf_counter()
    try:
        response = httpx.get(f"{app.target_url}/health", timeout=3)
        latency = round((time.perf_counter() - started) * 1000)
        return {"status": "up" if response.status_code == 200 else "error", "latency_ms": latency, "checked_at": time.time(),
                "window": "single probe at request time"}
    except httpx.HTTPError:
        return {"status": "unreachable", "latency_ms": None, "checked_at": time.time(), "window": "single probe at request time"}


def monitoring(s: Session, app: Application) -> dict:
    incidents = [{"id": i.id, "control": i.control_id, "severity": i.severity, "title": i.title, "state": i.state, "revision": i.revision,
                  "release": i.release, "cohort": i.cohort, "finding_id": i.finding_id, "closure": i.closure, "created_at": ts(i.created_at)}
                 for i in s.scalars(select(Incident).where(Incident.application_id == app.id).order_by(Incident.created_at.desc()))]
    events = [{"revision": e.revision, "source_id": e.source_id, "seq": e.seq, "epoch": e.epoch, "release": e.release, "type": e.event_type,
               "classification": e.classification, "trust_origin": e.trust_origin, "payload": e.payload, "received_at": ts(e.received_at)}
              for e in s.scalars(select(RuntimeEvent).where(RuntimeEvent.application_id == app.id, RuntimeEvent.event_type != "heartbeat")
                                 .order_by(RuntimeEvent.revision.desc()).limit(60))]
    return {"coverage": coverage(s, contract(s, app.id)), "incidents": incidents, "events": events, "health": probe_health(app),
            "mode": app.mode}


# ---------------- Overview ----------------

def overview(s: Session, app: Application) -> dict:
    release = latest_release(s, app.id)
    base = {"application": {"id": app.id, "name": app.name, "description": app.description, "environment": app.environment, "mode": app.mode},
            "runtime": coverage(s, contract(s, app.id)), "health": probe_health(app)}
    if release is None:
        return {**base, "release": None}
    state = reducer.readiness(s, app.id, release)
    prev = previous_release(s, release)
    change = s.scalars(select(ChangeSet).where(ChangeSet.target_release_id == release.id).order_by(ChangeSet.created_at.desc())).first()
    findings = [finding_json(f, s) for f in s.scalars(select(Finding).where(Finding.application_id == app.id).order_by(Finding.updated_at.desc()).limit(6))]
    trend = [{"release": p.release, "evidence_support": p.evidence_support, "evidence_coverage": p.evidence_coverage, "at": ts(p.created_at)}
             for p in s.scalars(select(ReadinessPoint).where(ReadinessPoint.application_id == app.id).order_by(ReadinessPoint.created_at))]
    running = s.scalars(select(Assessment).where(Assessment.application_id == app.id, Assessment.status.in_(["queued", "running"]))).first()
    last = s.scalars(select(Assessment).where(Assessment.application_id == app.id).order_by(Assessment.created_at.desc())).first()
    case = s.scalars(select(AssessmentCase).where(AssessmentCase.application_id == app.id).order_by(AssessmentCase.created_at.desc())).first()
    publication = s.scalars(select(ReportPublication).where(ReportPublication.application_id == app.id, ReportPublication.state == "published")
                            .order_by(ReportPublication.created_at.desc())).first()
    return {
        **base,
        "release": {**release_json(release), "previous": prev.version if prev else None},
        "readiness": state,
        "change": change_json(change) if change else (reducer.compare(s, app.id, prev, release) if prev else None),
        "findings": findings,
        "trend": trend,
        "assessment": {"running": assessment_json(running, s) if running else None, "last": assessment_json(last, s) if last else None},
        "case": {"id": case.id, "title": case.title, "state": case.state} if case else None,
        "publication": {"report_id": publication.report_id, "release": publication.release, "at": ts(publication.created_at)} if publication else None,
    }


# ---------------- Cases and reports ----------------

def case_json(c: AssessmentCase, s: Session, include_internal: bool) -> dict:
    messages = s.scalars(select(CaseMessage).where(CaseMessage.case_id == c.id).order_by(CaseMessage.created_at)).all()
    requests = s.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id == c.id).order_by(EvidenceRequest.created_at)).all()
    reports = s.scalars(select(Report).where(Report.case_id == c.id).order_by(Report.created_at.desc())).all()
    return {
        "id": c.id, "application_id": c.application_id, "title": c.title, "scope_note": c.scope_note, "state": c.state, "priority": c.priority,
        "revision": c.revision, "created_by": c.created_by, "created_at": ts(c.created_at), "updated_at": ts(c.updated_at),
        "messages": [{"id": m.id, "author": m.author, "author_kind": m.author_kind, "visibility": m.visibility, "body": m.body, "at": ts(m.created_at)}
                     for m in messages if include_internal or m.visibility == "customer"],
        "evidence_requests": [{"id": r.id, "requested_by": r.requested_by, "body": r.body, "state": r.state, "response": r.response,
                               "responded_by": r.responded_by, "at": ts(r.created_at)} for r in requests],
        "reports": [{"id": r.id, "state": r.state, "release": r.snapshot["release"]["version"], "sha256": r.sha256, "drafted_by": r.drafted_by,
                     "revision": r.revision, "at": ts(r.created_at)} for r in reports if include_internal or r.state in ("published", "superseded")],
    }


def build_snapshot(s: Session, app: Application, release: Release, case: AssessmentCase) -> dict:
    state = reducer.readiness(s, app.id, release)
    findings = [finding_json(f, s) for f in s.scalars(select(Finding).where(Finding.application_id == app.id))]
    evidence = [evidence_json(s.get(TestRun, t["run_id"]), s) for t in state["tests"] if t.get("run_id")]
    return {
        "application": {"id": app.id, "name": app.name, "environment": app.environment, "mode": app.mode},
        "case": {"id": case.id, "title": case.title, "scope_note": case.scope_note},
        "release": {"version": release.version, "manifest_hash": release.manifest_hash, "collection_status": release.collection_status},
        "profile": profile_version(), "readiness": state, "findings": findings, "evidence": evidence,
        "scope_note": "Readiness within the tested boundary of this release and environment. Not a certification, compliance or launch approval.",
        "generated_at": time.time(),
    }


def report_json(r: Report, s: Session, app: Application) -> dict:
    intact = canonical_hash(r.snapshot) == r.sha256
    current_release = latest_release(s, app.id)
    current = reducer.readiness(s, app.id, current_release) if current_release else None
    superseded = s.scalars(select(ReportPublication).where(ReportPublication.report_id == r.id)).first()
    return {
        "id": r.id, "state": r.state, "sha256": r.sha256, "integrity": "verified" if intact else "tampered", "revision": r.revision,
        "drafted_by": r.drafted_by, "snapshot": r.snapshot, "created_at": ts(r.created_at),
        "publication": {"state": superseded.state, "published_by": superseded.published_by, "at": ts(superseded.created_at)} if superseded else None,
        # Separate current-status banner: the frozen report never changes.
        "current_status": {"release": current["release"]["version"], "release_id": current_release.id, "manifest_hash": current_release.manifest_hash, "gate": current["gate"], "scores": current["scores"]} if current else None,
    }
