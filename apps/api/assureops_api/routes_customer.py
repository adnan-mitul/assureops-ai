"""Customer-company API surface (customer audience tokens only)."""

import time

import httpx
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import approvals, cases, evidence_store, reducer
from assureops_domain.db import tenant_session
from assureops_domain.models import (
    Application, Assessment, AssessmentCase, CaseMessage, ChangeSet, EvidenceRequest, Finding, FindingReview, Membership, Release,
    Report, ReportPublication, TestRun, User,
)
from assureops_domain.models import Workspace
from assureops_domain.profile import control_catalog, coverage_contract_for, profile_version, try_for_application

from . import services as svc
from .auth import Caller, CustomerCaller, api_error

router = APIRouter(prefix="/v1", tags=["customer"])
WRITE_ROLES = ("owner", "developer")
REVIEW_ROLES = ("owner", "reviewer")


def audit(s, caller: Caller, action: str, target: str, detail: dict | None = None):
    cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action=action, target=target, detail=detail)


@router.get("/me")
def me(caller: Caller = CustomerCaller):
    return {"user": caller.username, "display_name": caller.display_name, "workspace_id": caller.workspace_id, "role": caller.role,
            "memberships": caller.memberships}


# ---------------- Applications and releases ----------------

class ApplicationIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{3,40}$")
    name: str
    purpose: str
    environment: str = Field(pattern=r"^(staging|production)$")
    mode: str = Field(pattern=r"^(observe_only|enforce_supported_actions)$")
    target_url: str = ""
    tools_url: str = ""
    authorized_scope: dict = Field(default_factory=dict)


@router.post("/applications", status_code=201)
def register_application(body: ApplicationIn, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        if s.get(Application, body.id):
            raise api_error(409, "exists", "application id already used")
        s.add(Application(workspace_id=caller.workspace_id, description=body.purpose, **body.model_dump()))
        audit(s, caller, "application.register", body.id)
    return {"id": body.id}


@router.get("/applications")
def list_applications(caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        out = []
        for app in s.scalars(select(Application)):
            release = svc.latest_release(s, app.id)
            p = try_for_application(s, app.id)
            state = reducer.readiness(s, app.id, release, p) if release and p else None
            out.append({"id": app.id, "name": app.name, "description": app.description, "environment": app.environment, "mode": app.mode,
                        "release": release.version if release else None, "gate": state["gate"] if state else None,
                        "scores": state["scores"] if state else None, "profile": profile_version(p) if p else None,
                        "onboarding": svc.onboarding_status(s, app, p)})
        return out


@router.get("/applications/{application_id}/overview")
def application_overview(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        return svc.overview(s, svc.get_application(s, application_id))


@router.get("/applications/{application_id}/readiness")
def application_readiness(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        release = svc.latest_release(s, app.id)
        if release is None:
            raise api_error(409, "no_release", "no release has been collected")
        return reducer.readiness(s, app.id, release, svc.app_profile(s, app.id))


class ReleaseIn(BaseModel):
    source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    artifact_digest: str | None = Field(default=None, max_length=100)


@router.post("/applications/{application_id}/releases", status_code=201)
def submit_release(application_id: str, caller: Caller = CustomerCaller, body: ReleaseIn | None = None):
    caller.require_role(*WRITE_ROLES)
    body = body or ReleaseIn()
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        result = svc.collect_release(s, app, caller.username, source_commit=body.source_commit, artifact_digest=body.artifact_digest)
        if result["created"]:
            release = s.get(Release, result["release"]["id"])
            prev = svc.previous_release(s, release)
            change = svc.create_change_set(s, app, release, prev, caller.username)
            result["change_id"] = change.id
            for case in s.scalars(select(AssessmentCase).where(AssessmentCase.application_id == app.id, AssessmentCase.state.in_(["published", "monitoring"]))):
                if case.state == "published":
                    cases.transition(s, case, "monitoring")
                cases.transition(s, case, "reassessment")
        audit(s, caller, "release.submit", result["release"]["version"], {"created": result["created"], "gaps": result["gaps"]})
        return result


@router.get("/applications/{application_id}/releases")
def list_releases(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [svc.release_json(r) for r in s.scalars(select(Release).where(Release.application_id == application_id).order_by(Release.created_at.desc()))]


# ---------------- Changes ----------------

class CompareIn(BaseModel):
    application_id: str
    target_release_id: str
    base_release_id: str | None = None


@router.post("/changes/compare", status_code=201)
def compare(body: CompareIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES, "reviewer")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, body.application_id)
        target = s.get(Release, body.target_release_id)
        if target is None or target.application_id != app.id:
            raise api_error(404, "not_found", "release not found")
        base = s.get(Release, body.base_release_id) if body.base_release_id else svc.previous_release(s, target)
        return svc.change_json(svc.create_change_set(s, app, target, base, caller.username))


@router.get("/changes")
def list_changes(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [svc.change_json(c) for c in s.scalars(select(ChangeSet).where(ChangeSet.application_id == application_id).order_by(ChangeSet.created_at.desc()))]


@router.get("/changes/{change_id}")
def get_change(change_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        change = s.get(ChangeSet, change_id)
        if change is None:
            raise api_error(404, "not_found", "change not found")
        return svc.change_json(change)


@router.post("/changes/{change_id}/retests", status_code=202)
def schedule_retests(change_id: str, caller: Caller = CustomerCaller, idempotency_key: str | None = Header(default=None)):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        change = s.get(ChangeSet, change_id)
        if change is None:
            raise api_error(404, "not_found", "change not found")
        app = svc.get_application(s, change.application_id)
        target = s.get(Release, change.target_release_id)
        if svc.latest_release(s, app.id).id != target.id:
            raise api_error(409, "superseded", "a newer release exists; compare against it instead")
        case = s.scalars(select(AssessmentCase).where(AssessmentCase.application_id == app.id).order_by(AssessmentCase.created_at.desc())).first()
        job = svc.create_assessment(s, app, target, "retest", caller.username, case_id=case.id if case else None,
                                    idempotency_key=idempotency_key, plan_override=change.result["plan"])
        audit(s, caller, "retest.schedule", job.id, {"plan_id": change.plan_id})
        return {"id": job.id, "status": job.status, "plan_id": change.plan_id, "tests": job.plan["tests"]}


# ---------------- Assessments ----------------

class AssessmentIn(BaseModel):
    application_id: str
    release_id: str | None = None
    scope: str = Field(pattern=r"^(full|retest)$")


@router.post("/assessments", status_code=202)
def create_assessment(body: AssessmentIn, caller: Caller = CustomerCaller, idempotency_key: str | None = Header(default=None)):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, body.application_id)
        release = s.get(Release, body.release_id) if body.release_id else svc.latest_release(s, app.id)
        if release is None:
            raise api_error(409, "no_release", "submit a release before assessing")
        case = s.scalars(select(AssessmentCase).where(AssessmentCase.application_id == app.id).order_by(AssessmentCase.created_at.desc())).first()
        job = svc.create_assessment(s, app, release, body.scope, caller.username, case_id=case.id if case else None, idempotency_key=idempotency_key)
        audit(s, caller, "assessment.create", job.id, {"scope": body.scope})
        return {"id": job.id, "status": job.status, "plan_id": job.plan_id, "tests": job.plan["tests"]}


@router.get("/assessments")
def list_assessments(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [svc.assessment_json(a, s) for a in s.scalars(select(Assessment).where(Assessment.application_id == application_id).order_by(Assessment.created_at.desc()))]


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        job = s.get(Assessment, assessment_id)
        if job is None:
            raise api_error(404, "not_found", "assessment not found")
        return svc.assessment_json(job, s)


@router.get("/assessments/{assessment_id}/events")
def assessment_events(assessment_id: str, caller: Caller = CustomerCaller):
    """Progress feed. Clients reconnect by reloading this authoritative state."""
    with tenant_session(caller.workspace_id) as s:
        job = s.get(Assessment, assessment_id)
        if job is None:
            raise api_error(404, "not_found", "assessment not found")
        data = svc.assessment_json(job, s)
        return {"status": data["status"], "steps": data["steps"], "at": time.time()}


@router.post("/assessments/{assessment_id}/cancel")
def cancel_assessment(assessment_id: str, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        job = s.scalars(select(Assessment).where(Assessment.id == assessment_id).with_for_update()).first()
        if job is None:
            raise api_error(404, "not_found", "assessment not found")
        if job.status in ("completed", "failed", "cancelled"):
            return {"id": job.id, "status": job.status, "message": "already finished"}
        svc.cancel_assessment(s, job)
        audit(s, caller, "assessment.cancel", job.id)
        return {"id": job.id, "status": job.status, "cancel_requested": True}


# ---------------- Findings and evidence ----------------

@router.get("/findings")
def list_findings(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [svc.finding_json(f, s) for f in s.scalars(select(Finding).where(Finding.application_id == application_id).order_by(Finding.updated_at.desc()))]


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        f = s.get(Finding, finding_id)
        if f is None:
            raise api_error(404, "not_found", "finding not found")
        data = svc.finding_json(f, s, detail=True)
        data["evidence"] = [svc.evidence_json(s.get(TestRun, ref["run_id"]), s) for ref in f.evidence_refs if ref.get("run_id")]
        return data


class FindingReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(dispute|remediation_submitted)$")
    note: str = Field(min_length=3)
    expected_revision: int


@router.post("/findings/{finding_id}/reviews")
def review_finding(finding_id: str, body: FindingReviewIn, caller: Caller = CustomerCaller):
    caller.require_role("owner", "developer", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        f = s.scalars(select(Finding).where(Finding.id == finding_id).with_for_update()).first()
        if f is None:
            raise api_error(404, "not_found", "finding not found")
        if f.revision != body.expected_revision:
            raise api_error(409, "stale_revision", "the finding changed since you loaded it; reload and review again")
        if f.state == "resolved":
            raise api_error(409, "resolved", "resolved findings reopen only through new evidence")
        s.add(FindingReview(workspace_id=caller.workspace_id, finding_id=f.id, reviewer=caller.username, reviewer_kind="customer",
                            decision=body.decision, note=body.note, finding_revision=f.revision))
        if body.decision == "dispute":
            f.state = "under_review"  # existing failure is preserved until a reviewer decides
        else:
            f.remediation_note = body.note
        f.revision += 1
        f.updated_at = time.time()
        audit(s, caller, f"finding.{body.decision}", f.id)
        return svc.finding_json(f, s, detail=True)


@router.get("/evidence")
def list_evidence(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [svc.evidence_json(r, s) for r in s.scalars(select(TestRun).where(TestRun.application_id == application_id).order_by(TestRun.created_at.desc()).limit(150))]


@router.get("/evidence/{run_id}")
def get_evidence(run_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        run = s.get(TestRun, run_id)
        if run is None:
            raise api_error(404, "not_found", "evidence not found")
        return svc.evidence_json(run, s, with_record=True)


# ---------------- Approvals ----------------

class ApprovalIn(BaseModel):
    application_id: str
    requester: str
    order_id: str
    amount_minor: int = Field(gt=0)
    ttl_seconds: int = 600


@router.post("/approvals", status_code=201)
def grant_approval(body: ApprovalIn, caller: Caller = CustomerCaller):
    caller.require_role(*REVIEW_ROLES)
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, body.application_id)
        release = svc.latest_release(s, app.id)
        if release is None or "tool:issue_refund" not in release.manifest["components"]:
            raise api_error(409, "unsupported", "platform approvals apply to applications behind the AssureOps enforcement gateway")
        p = svc.app_profile(s, app.id)
        try:
            approval = approvals.grant(
                s, workspace_id=app.workspace_id, application_id=app.id, environment=app.environment, release=release.version, tool="issue_refund",
                tool_schema_hash=release.manifest["components"]["tool:issue_refund"]["fingerprint"],
                payload={"order_id": body.order_id, "amount_minor": body.amount_minor},
                permission_policy_version=release.manifest["policy_versions"]["permission"], requester=body.requester,
                approver=caller.username, ttl_seconds=body.ttl_seconds, self_approval_allowed=bool(p["requirements"].get("self_approval_allowed")))
        except approvals.ApprovalError as exc:
            raise api_error(422, exc.code, exc.detail)
        audit(s, caller, "approval.grant", approval.id, {"order_id": body.order_id, "amount_minor": body.amount_minor})
        return {"approval_id": approval.id, "expires_at": approval.expires_at, "bound_to": {"release": approval.release, "requester": approval.requester}}


# ---------------- Monitoring ----------------

@router.get("/monitoring")
def get_monitoring(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        return svc.monitoring(s, svc.get_application(s, application_id))


# ---------------- Cases ----------------

class CaseIn(BaseModel):
    application_id: str
    title: str = Field(min_length=3)
    scope_note: str = Field(min_length=3)


@router.get("/customer/cases")
def list_cases(caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        return [svc.case_json(c, s, include_internal=False) for c in s.scalars(select(AssessmentCase).order_by(AssessmentCase.created_at.desc()))]


@router.post("/customer/cases", status_code=201)
def submit_case(body: CaseIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, body.application_id)
        case = AssessmentCase(workspace_id=caller.workspace_id, application_id=body.application_id, title=body.title, scope_note=body.scope_note,
                              created_by=caller.username)
        s.add(case)
        s.flush()
        cases.sync_index(s, case)
        cases.transition(s, case, "submitted")
        audit(s, caller, "case.submit", case.id)
        return svc.case_json(case, s, include_internal=False)


@router.get("/customer/cases/{case_id}")
def get_case(case_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        if case is None:
            raise api_error(404, "not_found", "case not found")
        return svc.case_json(case, s, include_internal=False)


class ResponseIn(BaseModel):
    request_id: str
    response: str = Field(min_length=3)


@router.post("/customer/cases/{case_id}/responses")
def respond(case_id: str, body: ResponseIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES, "reviewer")
    with tenant_session(caller.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        request = s.get(EvidenceRequest, body.request_id)
        if case is None or request is None or request.case_id != case.id:
            raise api_error(404, "not_found", "evidence request not found")
        if request.state != "open":
            raise api_error(409, "answered", "this request was already answered")
        request.state, request.response, request.responded_by, request.answered_at = "answered", body.response, caller.username, time.time()
        open_left = s.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id == case.id, EvidenceRequest.state == "open")).first()
        if case.state == "awaiting_customer" and not open_left:
            cases.transition(s, case, "assessment")
        audit(s, caller, "case.respond", request.id)
        return svc.case_json(case, s, include_internal=False)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/customer/cases/{case_id}/messages", status_code=201)
def customer_message(case_id: str, body: MessageIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES, "reviewer")
    with tenant_session(caller.workspace_id) as s:
        if s.get(AssessmentCase, case_id) is None:
            raise api_error(404, "not_found", "case not found")
        s.add(CaseMessage(workspace_id=caller.workspace_id, case_id=case_id, author=caller.username, author_kind="customer", visibility="customer", body=body.body))
        return {"ok": True}


# ---------------- Reports ----------------

@router.get("/reports")
def list_reports(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        rows = s.scalars(select(ReportPublication).where(ReportPublication.application_id == application_id).order_by(ReportPublication.created_at.desc()))
        return [{"report_id": p.report_id, "release": p.release, "sha256": p.sha256, "state": p.state, "published_by": p.published_by,
                 "at": svc.ts(p.created_at)} for p in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        report = s.get(Report, report_id)
        if report is None or report.state not in ("published", "superseded"):  # drafts stay internal
            raise api_error(404, "not_found", "report not found")
        data = svc.report_json(report, s, svc.get_application(s, report.application_id))
        data["explanations"] = svc.explanations(s, report.id, accepted_only=True)
        return data


# ---------------- Settings ----------------

@router.get("/settings")
def get_settings(caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        members = [{"user": u.username, "name": u.display_name, "role": m.role}
                   for m, u in s.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                                         .where(Membership.workspace_id == caller.workspace_id, Membership.active.is_(True)))]
        apps, profiles = [], {}
        for a in s.scalars(select(Application)):
            apps.append({"id": a.id, "name": a.name, "mode": a.mode, "environment": a.environment, "target_url": a.target_url,
                         "tools_url": a.tools_url, "authorized_scope": a.authorized_scope})
            p = try_for_application(s, a.id)
            if p:
                profiles[a.id] = {"version": profile_version(p), "gate_policy": p["gate_policy"], "requirements": p["requirements"],
                                  "evidence_freshness_days": p["evidence_freshness_days"], "assessed_controls": p["assessed_controls"],
                                  "unassessed_controls": p["unassessed_controls"]}
        ws = s.get(Workspace, caller.workspace_id)
        first = next(iter(profiles.values()), None)
        from . import ai_routes
        return {
            "workspace": caller.workspace_id, "your_role": caller.role, "members": members, "applications": apps,
            "profile": {**(first or {}), "controls": control_catalog()["controls"], "version": (first or {}).get("version", "none"),
                        "gate_policy": (first or {}).get("gate_policy", {"version": "-", "blocking_severities": []}),
                        "requirements": (first or {}).get("requirements", {}),
                        "evidence_freshness_days": (first or {}).get("evidence_freshness_days", 30)},
            "profiles": profiles,
            "data_policy": {"inference": "private_and_approved_external" if ws and ws.external_processing else "private_only",
                            "external_processing": bool(ws and ws.external_processing), "training_on_customer_evidence": False},
            "model_routes": ai_routes.route_table(ws), "retention": {"evidence_days": 365, "runtime_events_days": 90},
        }


# ---------------- Demo helpers (synthetic target only) ----------------

class DeployIn(BaseModel):
    application_id: str
    release: str = Field(pattern=r"^R[0-9]+$")


@router.post("/demo/deploy")
def demo_deploy(body: DeployIn, caller: Caller = CustomerCaller):
    """Synthetic labs only: switch the lab's release through its declared release switch, then submit it as a new release."""
    caller.require_role(*WRITE_ROLES)
    from assureops_domain import connections

    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, body.application_id)
        conn = connections.latest_connection(s, app.id)
        switch = ((conn.config.get("lab") or {}).get("release_switch") if conn else None)
        if conn and conn.adapter_id != "assureops-mcp-reference" and not switch:
            raise api_error(409, "unsupported", "this connection declares no synthetic-lab release switch; deploy through your own pipeline")
        spec, problems = connections.spec_for(s, conn, with_credentials=True) if conn else (None, [])
    try:
        if switch:
            from assureops_connectors.http_json import HttpJsonAdapter

            client = HttpJsonAdapter().client(spec)
            try:
                result = client.request(switch.get("method", "POST"), switch["path"], actor=switch.get("actor"),
                                        body={switch.get("field", "release"): body.release}, enforce_scope=False)
            finally:
                client.close()
            if result["status"] != 200:
                raise api_error(502, "switch_failed", f"lab release switch answered HTTP {result['status']}")
        else:
            httpx.post(f"{app.target_url}/admin/release", json={"release": body.release}, timeout=5).raise_for_status()
    except httpx.HTTPError as exc:
        raise api_error(502, "target_unreachable", f"could not switch release: {exc.__class__.__name__}")
    return submit_release(body.application_id, caller)


class DemoChatIn(BaseModel):
    application_id: str
    message: str = Field(min_length=1, max_length=500)
    user: str = "customer:C-2041"
    approval_id: str | None = None


@router.post("/demo/chat")
def demo_chat(body: DemoChatIn, caller: Caller = CustomerCaller):
    """Demo only: ordinary (non-test) customer traffic so runtime monitoring has something to observe."""
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        target_url = svc.get_application(s, body.application_id).target_url
    try:
        response = httpx.post(f"{target_url}/chat", json={"message": body.message, "user": body.user, "approval_id": body.approval_id}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise api_error(502, "target_unreachable", f"target unavailable: {exc.__class__.__name__}")
    return response.json()
