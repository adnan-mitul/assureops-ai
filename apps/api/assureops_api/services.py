"""Shared domain operations used by both portals' routes and the integration surface.

Callers authorize first and pass a tenant-scoped session; nothing here reads
another workspace's rows. Every readiness computation uses the application's
own active profile.
"""

import time

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assureops_domain import connections, evidence_store, reducer
from assureops_domain.config import settings
from assureops_domain.events import coverage
from assureops_domain.models import (
    Application, ApplicationProfile, Artifact, Assessment, AssessmentCase, CaseMessage, ChangeSet, ConnectorSecret, CoverageContract,
    EvidenceRequest, EvidenceReview, Finding, FindingReview, Incident, JobStep, Outbox, ReadinessPoint, Release, Report, ReportPublication,
    RuntimeEvent, TestRun, Workspace,
)
from assureops_domain.profile import (
    ProfileError, canonical_hash, control_catalog, coverage_contract_for, for_application, profile_version, try_for_application,
)

from .auth import api_error


def ts(value):
    return round(value, 3) if value else value


def app_profile(s: Session, application_id: str) -> dict:
    try:
        return for_application(s, application_id)
    except ProfileError as exc:
        raise api_error(409, exc.code, exc.detail)


def control_name(control_id: str) -> str:
    return control_catalog()["controls"].get(control_id, {}).get("name", control_id)


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
            "collection_status": r.collection_status, "collection_gaps": r.collection_gaps, "created_at": ts(r.created_at),
            "source_commit": r.source_commit, "artifact_digest": r.artifact_digest, "profile_revision": r.profile_revision,
            "connection_revision": r.connection_revision}


# ---------------- Releases ----------------

def collect_release(s: Session, app: Application, actor: str, *, source_commit: str | None = None, artifact_digest: str | None = None) -> dict:
    """Collect the manifest through the verified connection and record an immutable release.

    Release identity is (declared version, component hash): the same components under a new version are a new
    release, and a reused version label with different components is a new release flagged as a collection gap.
    """
    try:
        conn = connections.require_verified(s, app.id)
    except connections.OnboardingError as exc:
        raise api_error(409, exc.code, exc.detail)
    p = app_profile(s, app.id)
    base = connections.adapters()
    spec, _ = connections.spec_for(s, conn, with_credentials=False)
    try:
        collected = base.get(conn.adapter_id).collect_manifest(spec)
    except base.AdapterError as exc:
        raise api_error(502 if exc.code == "target_unreachable" else 422, exc.code, exc.detail)
    manifest, gaps = collected["manifest"], list(collected["gaps"])
    mandatory = coverage_contract_for(p).get("mandatory_components", {})
    groups = mandatory.values() if isinstance(mandatory, dict) else [mandatory]
    required = {c for comps in groups for c in comps}
    gaps += [f"mandatory component not collected: {c}" for c in sorted(required - set(manifest["components"]))]
    manifest_hash = canonical_hash(manifest["components"])
    existing = s.scalars(select(Release).where(Release.application_id == app.id, Release.version == manifest["release"],
                                               Release.manifest_hash == manifest_hash)).first()
    if existing:
        return {"release": release_json(existing), "created": False, "gaps": existing.collection_gaps}
    if s.scalars(select(Release).where(Release.application_id == app.id, Release.version == manifest["release"])).first():
        gaps.append(f"version label {manifest['release']} was already used with different components; identity is ambiguous")
    release = Release(workspace_id=app.workspace_id, application_id=app.id, version=manifest["release"], manifest=manifest,
                      manifest_hash=manifest_hash, collection_gaps=gaps, collection_status="partial" if gaps else "complete", collected_by=actor,
                      source_commit=source_commit, artifact_digest=artifact_digest, profile_revision=p["revision"], connection_revision=conn.revision)
    s.add(release)
    s.flush()
    return {"release": release_json(release), "created": True, "gaps": gaps}


# ---------------- Assessments ----------------

def check_quota(s: Session, app: Application):
    """Tenant admission control: per-day assessment budget."""
    ws = s.get(Workspace, app.workspace_id)
    used = s.scalar(select(func.count()).select_from(Assessment).where(Assessment.created_at > time.time() - 86400)) or 0
    if ws and used >= ws.assessments_per_day:
        raise api_error(429, "quota_exceeded", f"workspace assessment budget of {ws.assessments_per_day} per day is used up")


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
    try:
        conn = connections.require_verified(s, app.id)
    except connections.OnboardingError as exc:
        raise api_error(409, exc.code, exc.detail)
    check_quota(s, app)
    p = app_profile(s, app.id)
    state = reducer.readiness(s, app.id, release, p)
    tests = plan_override if plan_override is not None else reducer.retest_plan(state, scope, p)
    unknown = sorted(set(tests) - set(p["tests_by_id"]))
    if unknown:
        raise api_error(409, "plan_outdated", f"plan references tests not in the active profile: {unknown}; compare again")
    edges = reducer.accepted_edges(s, app.id, p)
    adapter = connections.adapters().get(conn.adapter_id)
    frozen = {
        "release": {"id": release.id, "version": release.version, "manifest_hash": release.manifest_hash, "manifest": release.manifest},
        "environment": app.environment,
        "profile": {"revision": p["revision"], "version": profile_version(p), "digest": p["digest"]},
        "connection": {"revision": conn.revision, "adapter_id": conn.adapter_id, "adapter_version": conn.adapter_version,
                       "evaluator_version": adapter.evaluator_version},
        "edge_revision": reducer.edge_revision(edges),
        "tests": {tid: p["tests_by_id"][tid] for tid in tests},
    }
    plan_id = canonical_hash({"release": release.id, "tests": tests, "profile": p["digest"], "edges": frozen["edge_revision"],
                              "connection": conn.revision})[:16]
    job = Assessment(workspace_id=app.workspace_id, application_id=app.id, release_id=release.id, case_id=case_id, scope=scope, plan_id=plan_id,
                     plan={"tests": tests}, profile_version=profile_version(p), edge_revision=frozen["edge_revision"], frozen=frozen,
                     idempotency_key=idempotency_key, request_hash=request_hash, requested_by=actor)
    s.add(job)
    s.flush()
    for position, test_id in enumerate(tests):
        step = JobStep(workspace_id=app.workspace_id, assessment_id=job.id, step_key=f"{job.id}:{test_id}", test_id=test_id,
                       position=position, max_attempts=3)
        s.add(step)
        s.flush()
        # Outbox row commits in the same transaction as the domain transition.
        s.add(Outbox(workspace_id=app.workspace_id, kind="run_step", ref_id=step.id))
    if not tests:
        s.add(Outbox(workspace_id=app.workspace_id, kind="finalize_assessment", ref_id=job.id))
    return job


def cancel_assessment(s: Session, job: Assessment) -> Assessment:
    """Stops pending work and finalizes once running steps return; evidence already committed stays."""
    job.cancel_requested = True
    for step in s.scalars(select(JobStep).where(JobStep.assessment_id == job.id, JobStep.status == "pending")):
        step.status, step.finished_at = "cancelled", time.time()
    s.add(Outbox(workspace_id=job.workspace_id, kind="finalize_assessment", ref_id=job.id))
    return job


def assessment_json(a: Assessment, s: Session) -> dict:
    steps = s.scalars(select(JobStep).where(JobStep.assessment_id == a.id).order_by(JobStep.position)).all()
    outcomes = {r.id: r.outcome for r in s.scalars(select(TestRun).where(TestRun.assessment_id == a.id))}
    release = s.get(Release, a.release_id)
    frozen = a.frozen or {}
    return {
        "id": a.id, "application_id": a.application_id, "release": release.version if release else None, "scope": a.scope, "status": a.status, "plan_id": a.plan_id,
        "profile_version": a.profile_version, "tests": a.plan.get("tests", []), "case_id": a.case_id, "requested_by": a.requested_by,
        "frozen": {"profile": frozen.get("profile"), "connection": frozen.get("connection"), "edge_revision": frozen.get("edge_revision"),
                   "release": {k: v for k, v in frozen.get("release", {}).items() if k != "manifest"}},
        "steps": [{"test_id": st.test_id, "status": st.status, "attempt": st.attempt, "error": st.last_error, "run_id": st.result_run_id,
                   "outcome": outcomes.get(st.result_run_id)} for st in steps],
        "summary": a.summary, "error": a.error, "cancel_requested": a.cancel_requested,
        "created_at": ts(a.created_at), "finished_at": ts(a.finished_at),
    }


# ---------------- Changes ----------------

def create_change_set(s: Session, app: Application, target: Release, base: Release | None, actor: str) -> ChangeSet:
    p = app_profile(s, app.id)
    result = reducer.compare(s, app.id, base, target, p)
    state = reducer.readiness(s, app.id, target, p)
    plan = reducer.retest_plan(state, "retest", p)
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
    data = {"id": f.id, "control": f.control_id, "control_name": control_name(f.control_id), "test_id": f.test_id,
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
    job = s.get(Assessment, run.assessment_id)
    test = ((job.frozen or {}).get("tests") or {}).get(run.test_id) if job else None
    if test is None:
        test = (try_for_application(s, run.application_id) or {"tests_by_id": {}})["tests_by_id"].get(run.test_id, {"name": run.test_id})
    data = {
        "id": run.id, "test_id": run.test_id, "test_name": test["name"], "control": run.control_id,
        "control_name": control_name(run.control_id), "claim": test["name"], "release": release.version, "template": test.get("template"),
        "outcome": run.outcome, "trials": run.trials, "passed_trials": run.passed_trials, "trial_outcomes": run.trial_outcomes,
        "expected": run.expected, "observation_source": run.observation_source, "origin": "tested",
        "collection_scope": f"{release.version} · {job.frozen.get('environment', 'staging') if job else 'staging'} · profile {run.profile_version}",
        "dependency_fingerprints": run.dependency_fingerprints, "evidence_hash": artifact.sha256 if artifact else None,
        "available": evidence_store.available(artifact), "model_role": "none — deterministic test and rules",
        "test_digest": run.test_digest, "evaluator_version": run.evaluator_version,
        "review": {"reviewer": review.reviewer, "decision": review.decision, "note": review.note, "at": ts(review.created_at)} if review else None,
        "created_at": ts(run.created_at),
    }
    if with_record:
        try:
            data["record"] = evidence_store.read_json(artifact)
        except evidence_store.EvidenceUnavailable as exc:
            data["record"], data["unavailable_reason"] = None, str(exc)
    return data


# ---------------- Connections and onboarding ----------------

def connection_json(s: Session, app: Application) -> dict | None:
    from assureops_domain import vault

    conn = connections.latest_connection(s, app.id)
    if conn is None:
        return None
    secrets = {r.id: vault.describe(r) for r in s.scalars(select(ConnectorSecret).where(ConnectorSecret.application_id == app.id))}
    actors = {name: {"secret": secrets.get(ref.get("secret_id"))} for name, ref in (conn.config.get("actors") or {}).items()}
    return {"id": conn.id, "revision": conn.revision, "adapter_id": conn.adapter_id, "adapter_version": conn.adapter_version,
            "status": conn.status, "config": {k: v for k, v in conn.config.items() if k != "actors"}, "actors": actors,
            "verification": conn.verification, "verified_at": ts(conn.verified_at), "created_by": conn.created_by,
            "created_at": ts(conn.created_at)}


def profile_row_json(row: ApplicationProfile) -> dict:
    tests = row.profile.get("tests", [])
    assessed = sorted({t["control"] for t in tests})
    return {"revision": row.revision, "status": row.status, "source": row.source, "proposed_by": row.proposed_by,
            "reviewed_by": row.reviewed_by, "review_note": row.review_note, "digest": row.digest[:16],
            "profile_id": row.profile.get("profile_id"), "version": row.profile.get("version"), "adapter": row.profile.get("adapter"),
            "scope": (row.profile.get("scope") or {}).get("statement"), "assessed_controls": assessed,
            "unassessed_controls": sorted(set(control_catalog()["controls"]) - set(assessed)),
            "tests": [{k: t.get(k) for k in ("id", "control", "severity", "name", "expected", "template", "trials", "mandatory", "requires_review")}
                      for t in tests],
            "created_at": ts(row.created_at), "activated_at": ts(row.activated_at)}


def onboarding_status(s: Session, app: Application, p: dict | None) -> dict:
    conn = connections.latest_connection(s, app.id)
    proposed = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id, ApplicationProfile.status == "proposed")
                         .order_by(ApplicationProfile.revision.desc())).first()
    steps = [
        {"id": "connect", "label": "Connect the application", "done": conn is not None},
        {"id": "verify", "label": "Verify connection, scope and credentials", "done": bool(conn and conn.status == "verified")},
        {"id": "profile", "label": "Review and activate a control profile", "done": p is not None},
        {"id": "release", "label": "Submit a release", "done": latest_release(s, app.id) is not None},
    ]
    return {"steps": steps, "complete": all(x["done"] for x in steps),
            "connection": {"status": conn.status, "revision": conn.revision, "adapter_id": conn.adapter_id,
                           "gaps": (conn.verification or {}).get("gaps", [])} if conn else None,
            "profile": {"version": profile_version(p), "assessed_controls": p["assessed_controls"],
                        "unassessed_controls": p["unassessed_controls"], "tests": len(p["tests"])} if p else None,
            "proposed_profile_revision": proposed.revision if proposed else None}


# ---------------- Monitoring and health ----------------

def probe_health(s: Session, app: Application) -> dict:
    """Operational health of the assessed application, measured separately from assessment coverage."""
    from assureops_connectors.egress import EgressDenied, check_target

    conn = connections.latest_connection(s, app.id)
    path = (conn.config.get("health_path") if conn else None) or "/health"
    try:
        target = check_target(app.target_url, allow_private=settings().allow_private_targets)
    except EgressDenied as exc:
        return {"status": "not_reachable", "latency_ms": None, "checked_at": time.time(), "window": str(exc)}
    started = time.perf_counter()
    try:
        response = httpx.get(f"{target['origin']}{path}", timeout=3, follow_redirects=False, trust_env=False)
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
    latest = latest_release(s, app.id)
    return {"coverage": coverage(s, contract(s, app.id), expected_release=latest.version if latest else None), "incidents": incidents,
            "events": events, "health": probe_health(s, app),
            "mode": app.mode}


# ---------------- Overview ----------------

def overview(s: Session, app: Application) -> dict:
    release = latest_release(s, app.id)
    p = try_for_application(s, app.id)
    base = {"application": {"id": app.id, "name": app.name, "description": app.description, "environment": app.environment, "mode": app.mode},
            "runtime": coverage(s, contract(s, app.id), expected_release=release.version if release else None), "health": probe_health(s, app),
            "onboarding": onboarding_status(s, app, p)}
    if release is None or p is None:
        return {**base, "release": None}
    state = reducer.readiness(s, app.id, release, p)
    prev = previous_release(s, release)
    change = s.scalars(select(ChangeSet).where(ChangeSet.target_release_id == release.id).order_by(ChangeSet.created_at.desc())).first()
    findings = [finding_json(f, s) for f in s.scalars(select(Finding).where(Finding.application_id == app.id).order_by(Finding.updated_at.desc()).limit(6))]
    trend = [{"release": pt.release, "evidence_support": pt.evidence_support, "evidence_coverage": pt.evidence_coverage, "at": ts(pt.created_at)}
             for pt in s.scalars(select(ReadinessPoint).where(ReadinessPoint.application_id == app.id).order_by(ReadinessPoint.created_at))]
    running = s.scalars(select(Assessment).where(Assessment.application_id == app.id, Assessment.status.in_(["queued", "running"]))).first()
    last = s.scalars(select(Assessment).where(Assessment.application_id == app.id).order_by(Assessment.created_at.desc())).first()
    case = s.scalars(select(AssessmentCase).where(AssessmentCase.application_id == app.id).order_by(AssessmentCase.created_at.desc())).first()
    publication = s.scalars(select(ReportPublication).where(ReportPublication.application_id == app.id, ReportPublication.state == "published")
                            .order_by(ReportPublication.created_at.desc())).first()
    return {
        **base,
        "release": {**release_json(release), "previous": prev.version if prev else None},
        "readiness": state,
        "change": change_json(change) if change else (reducer.compare(s, app.id, prev, release, p) if prev else None),
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
    p = app_profile(s, app.id)
    state = reducer.readiness(s, app.id, release, p)
    findings = [finding_json(f, s) for f in s.scalars(select(Finding).where(Finding.application_id == app.id))]
    evidence = [evidence_json(s.get(TestRun, t["run_id"]), s) for t in state["tests"] if t.get("run_id")]
    return {
        "application": {"id": app.id, "name": app.name, "environment": app.environment, "mode": app.mode},
        "case": {"id": case.id, "title": case.title, "scope_note": case.scope_note},
        "release": {"version": release.version, "manifest_hash": release.manifest_hash, "collection_status": release.collection_status,
                    "source_commit": release.source_commit},
        "profile": profile_version(p), "readiness": state, "findings": findings, "evidence": evidence,
        "incidents": [{"id": i.id, "control": i.control_id, "state": i.state, "revision": i.revision}
                      for i in s.scalars(select(Incident).where(Incident.application_id == app.id))],
        "unassessed_controls": [{"id": c["id"], "name": c["name"]} for c in state["controls"] if c["result"] == "unassessed"],
        "scope_note": ("Readiness within the tested boundary of this release, environment and profile. Controls outside the profile are "
                       "listed as not assessed. Not a certification, compliance or launch approval."),
        "generated_at": time.time(),
    }


def publication_drift(s: Session, report: Report) -> list[str]:
    """Reasons a drafted snapshot no longer describes reality; any reason blocks publication (plan I1)."""
    latest = latest_release(s, report.application_id)
    if latest is None or latest.id != report.release_id:
        return [f"a newer release ({latest.version if latest else 'unknown'}) exists; draft a new snapshot"]
    p = try_for_application(s, report.application_id)
    if p is None:
        return ["the application has no active profile"]
    reasons = []
    if profile_version(p) != report.snapshot.get("profile"):
        reasons.append(f"the active profile changed to {profile_version(p)}")
    state = reducer.readiness(s, report.application_id, latest, p)
    if state["evidence_digest"] != report.snapshot["readiness"].get("evidence_digest"):
        reasons.append("evidence changed since the draft (new, deleted, reviewed or invalidated runs)")
    known = {(i["id"], i["revision"]) for i in report.snapshot.get("incidents", [])}
    current = {(i.id, i.revision) for i in s.scalars(select(Incident).where(Incident.application_id == report.application_id))}
    if current - known:
        reasons.append("an incident was opened or changed after the draft")
    if canonical_hash(report.snapshot) != report.sha256:
        reasons.append("snapshot integrity check failed")
    return reasons


def explanations(s: Session, report_id: str, *, accepted_only: bool) -> list[dict]:
    """Phase F drafts for one frozen report. They explain; the snapshot's verdicts and numbers stay authoritative."""
    from assureops_domain.models import AiResult

    rows = s.scalars(select(AiResult).where(AiResult.phase == "F").order_by(AiResult.created_at.desc())).all()
    out = []
    for r in rows:
        if (r.request.get("refs") or {}).get("report_id") != report_id:
            continue
        if accepted_only and r.status != "accepted":
            continue
        out.append({"id": r.id, "status": r.status, "sections": (r.output or {}).get("sections", []), "provider": r.versions.get("provider"),
                    "model": r.versions.get("model"), "reviewer": r.reviewer, "at": ts(r.updated_at)})
    return out


def report_json(r: Report, s: Session, app: Application) -> dict:
    intact = canonical_hash(r.snapshot) == r.sha256
    current_release = latest_release(s, app.id)
    p = try_for_application(s, app.id)
    current = reducer.readiness(s, app.id, current_release, p) if current_release and p else None
    superseded = s.scalars(select(ReportPublication).where(ReportPublication.report_id == r.id)).first()
    return {
        "id": r.id, "state": r.state, "sha256": r.sha256, "integrity": "verified" if intact else "tampered", "revision": r.revision,
        "drafted_by": r.drafted_by, "snapshot": r.snapshot, "created_at": ts(r.created_at),
        "publication": {"state": superseded.state, "published_by": superseded.published_by, "at": ts(superseded.created_at)} if superseded else None,
        # Separate current-status banner: the frozen report never changes.
        "current_status": {"release": current["release"]["version"], "release_id": current_release.id, "manifest_hash": current_release.manifest_hash,
                           "gate": current["gate"], "scores": current["scores"]} if current else None,
    }
