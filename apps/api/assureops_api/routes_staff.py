"""AssureOps staff API surface (staff audience tokens only).

Staff reach customer content only through an active case assignment; the API
resolves the case-scoped grant, then sets the tenant context for that one
workspace. Case managers see queue metadata, never raw evidence.
"""

import time

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from assureops_domain import cases, connections, reducer
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.findings import FindingError, close_incident
from assureops_domain.models import (
    Assessment, AssessmentCase, CaseAssignment, CaseIndex, CaseMessage, ChangeSet, DependencyEdge, EvidenceRequest, EvidenceReview, Finding,
    FindingReview, Incident, JobStep, ModelQualification, Outbox, Release, Report, ReportPublication, ReviewDecision, RuntimeEvent, StaffRole,
    TestRun, User, Workspace,
)
from assureops_domain.profile import ProfileError, canonical_hash, control_catalog, profile_version, try_for_application

from assureops_domain.config import settings

from . import ai_routes
from . import services as svc
from .auth import Caller, StaffCaller, api_error

router = APIRouter(prefix="/v1/staff", tags=["staff"])


def assignment(caller: Caller, case_id: str, *duties: str) -> CaseAssignment:
    with platform_session() as s:
        rows = s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.staff_user_id == caller.user_id,
                                                      CaseAssignment.active.is_(True))).all()
    needed = {"analyst": "analyst", "reviewer": "senior_reviewer"}
    match = next((a for a in rows if (not duties or a.duty in duties) and needed.get(a.duty, a.duty) in caller.staff_roles), None)
    if match is None:
        raise api_error(403, "not_assigned", "this case is not assigned to you (or the role for that duty was revoked)")
    return match


def audit(s, workspace_id: str, caller: Caller, action: str, target: str, detail: dict | None = None):
    cases.audit(s, workspace_id=workspace_id, actor=caller.username, actor_kind="staff", action=action, target=target, detail=detail)


@router.get("/me")
def me(caller: Caller = StaffCaller):
    return {"user": caller.username, "display_name": caller.display_name, "roles": sorted(caller.staff_roles)}


# ---------------- Queues ----------------

@router.get("/work-queue")
def work_queue(caller: Caller = StaffCaller):
    with platform_session() as s:
        mine = s.scalars(select(CaseAssignment).where(CaseAssignment.staff_user_id == caller.user_id, CaseAssignment.active.is_(True))).all()
        duties = {a.case_id: a.duty for a in mine}
        rows = s.scalars(select(CaseIndex).order_by(CaseIndex.updated_at.desc())).all()
        staff_names = {u.id: u.username for u in s.scalars(select(User).where(User.kind == "staff"))}
        all_assignments = s.scalars(select(CaseAssignment).where(CaseAssignment.active.is_(True))).all()
        out = []
        for row in rows:
            visible = row.case_id in duties or "case_manager" in caller.staff_roles or (row.state in ("submitted", "triage") and "analyst" in caller.staff_roles)
            if not visible:
                continue
            out.append({"case_id": row.case_id, "workspace": row.workspace_name, "application": row.application_name, "title": row.title,
                        "state": row.state, "priority": row.priority, "blockers": row.blockers, "updated_at": svc.ts(row.updated_at),
                        "queue_age_hours": round((time.time() - row.updated_at) / 3600, 1), "your_duty": duties.get(row.case_id),
                        "assignees": [{"user": staff_names.get(a.staff_user_id), "duty": a.duty} for a in all_assignments if a.case_id == row.case_id]})
        return out


@router.get("/review-queue")
def review_queue(caller: Caller = StaffCaller):
    caller.require_staff("senior_reviewer")
    with platform_session() as s:
        mine = s.scalars(select(CaseAssignment).where(CaseAssignment.staff_user_id == caller.user_id, CaseAssignment.duty == "reviewer",
                                                      CaseAssignment.active.is_(True))).all()
    out = []
    for a in mine:
        with tenant_session(a.workspace_id) as s:
            case = s.get(AssessmentCase, a.case_id)
            for r in s.scalars(select(Report).where(Report.case_id == a.case_id, Report.state == "draft")):
                out.append({"case_id": case.id, "case_title": case.title, "report_id": r.id, "release": r.snapshot["release"]["version"],
                            "drafted_by": r.drafted_by, "revision": r.revision, "gate": r.snapshot["readiness"]["gate"]["status"],
                            "at": svc.ts(r.created_at)})
    return out


# ---------------- Assignment ----------------

class AssignIn(BaseModel):
    staff_user: str
    duty: str = Field(pattern=r"^(analyst|reviewer)$")


@router.post("/cases/{case_id}/assignments", status_code=201)
def assign(case_id: str, body: AssignIn, caller: Caller = StaffCaller):
    caller.require_staff("case_manager", "admin")
    with platform_session() as s:
        index = s.get(CaseIndex, case_id)
        user = s.scalars(select(User).where(User.username == body.staff_user, User.kind == "staff")).first()
        if index is None or user is None:
            raise api_error(404, "not_found", "case or staff user not found")
        needed = {"analyst": "analyst", "reviewer": "senior_reviewer"}[body.duty]
        if not s.scalars(select(StaffRole).where(StaffRole.user_id == user.id, StaffRole.role == needed, StaffRole.active.is_(True))).first():
            raise api_error(422, "missing_role", f"{body.staff_user} lacks the {needed} role")
        other = s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.staff_user_id == user.id,
                                                       CaseAssignment.active.is_(True))).first()
        if other and other.duty != body.duty:
            raise api_error(422, "separation_of_duties", "the analyst and the independent reviewer must be different people")
        if not other:
            s.add(CaseAssignment(case_id=case_id, workspace_id=index.workspace_id, staff_user_id=user.id, duty=body.duty, granted_by=caller.username))
        workspace_id = index.workspace_id
    with tenant_session(workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        if case.state == "submitted":
            cases.transition(s, case, "triage")
        analysts = _has_duty(case_id, "analyst") or body.duty == "analyst"
        if case.state == "triage" and analysts:
            cases.transition(s, case, "assessment")
        audit(s, workspace_id, caller, "case.assign", case_id, {"staff_user": body.staff_user, "duty": body.duty})
    return {"ok": True}


def _has_duty(case_id: str, duty: str) -> bool:
    with platform_session() as s:
        return s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.duty == duty, CaseAssignment.active.is_(True))).first() is not None


@router.post("/cases/{case_id}/claim", status_code=201)
def claim(case_id: str, caller: Caller = StaffCaller):
    """An analyst may claim an untriaged case that has no analyst yet."""
    caller.require_staff("analyst")
    with platform_session() as s:
        index = s.get(CaseIndex, case_id)
        if index is None or index.state not in ("submitted", "triage"):
            raise api_error(409, "not_claimable", "only newly submitted cases can be claimed")
        if s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.duty == "analyst", CaseAssignment.active.is_(True))).first():
            raise api_error(409, "already_claimed", "an analyst is already assigned")
        s.add(CaseAssignment(case_id=case_id, workspace_id=index.workspace_id, staff_user_id=caller.user_id, duty="analyst", granted_by=f"claim:{caller.username}"))
        workspace_id = index.workspace_id
    with tenant_session(workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        if case.state == "submitted":
            cases.transition(s, case, "triage")
        cases.transition(s, case, "assessment")
        audit(s, workspace_id, caller, "case.claim", case_id)
    return {"ok": True}


@router.delete("/cases/{case_id}/assignments/{staff_user}")
def revoke_assignment(case_id: str, staff_user: str, caller: Caller = StaffCaller):
    caller.require_staff("case_manager", "admin")
    with platform_session() as s:
        user = s.scalars(select(User).where(User.username == staff_user)).first()
        rows = s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.staff_user_id == (user.id if user else ""),
                                                      CaseAssignment.active.is_(True))).all()
        if not rows:
            raise api_error(404, "not_found", "no active assignment for that user on this case")
        for row in rows:
            row.active, row.revoked_at = False, time.time()
        workspace_id = rows[0].workspace_id
    with tenant_session(workspace_id) as s:
        audit(s, workspace_id, caller, "case.unassign", case_id, {"staff_user": staff_user})
    return {"revoked": len(rows)}


class ReassignIn(BaseModel):
    duty: str = Field(pattern=r"^(analyst|reviewer)$")
    from_user: str
    to_user: str


@router.post("/cases/{case_id}/reassign")
def reassign(case_id: str, body: ReassignIn, caller: Caller = StaffCaller):
    """Move one duty from one person to another in a single transaction; separation of duties still holds."""
    caller.require_staff("case_manager", "admin")
    if body.from_user == body.to_user:
        raise api_error(422, "same_user", "choose a different person")
    with platform_session() as s:
        users = {u.username: u for u in s.scalars(select(User).where(User.username.in_([body.from_user, body.to_user]), User.kind == "staff"))}
        if len(users) != 2:
            raise api_error(404, "not_found", "staff user not found")
        current = s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.staff_user_id == users[body.from_user].id,
                                                         CaseAssignment.duty == body.duty, CaseAssignment.active.is_(True)).with_for_update()).first()
        if current is None:
            raise api_error(404, "not_found", f"{body.from_user} does not hold the {body.duty} duty on this case")
        target = users[body.to_user]
        needed = {"analyst": "analyst", "reviewer": "senior_reviewer"}[body.duty]
        if not s.scalars(select(StaffRole).where(StaffRole.user_id == target.id, StaffRole.role == needed, StaffRole.active.is_(True))).first():
            raise api_error(422, "missing_role", f"{body.to_user} lacks the {needed} role")
        if s.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case_id, CaseAssignment.staff_user_id == target.id,
                                                  CaseAssignment.active.is_(True))).first():
            raise api_error(422, "separation_of_duties", f"{body.to_user} already holds a duty on this case")
        current.active, current.revoked_at = False, time.time()
        s.add(CaseAssignment(case_id=case_id, workspace_id=current.workspace_id, staff_user_id=target.id, duty=body.duty,
                             granted_by=f"reassign:{caller.username}"))
        workspace_id = current.workspace_id
    with tenant_session(workspace_id) as s:
        audit(s, workspace_id, caller, "case.reassign", case_id, body.model_dump())
    return {"ok": True, "duty": body.duty, "to": body.to_user}


# ---------------- Case workspace ----------------

def _case_bundle(s, case: AssessmentCase) -> dict:
    app = svc.get_application(s, case.application_id)
    data = svc.case_json(case, s, include_internal=True)
    data["application"] = {"id": app.id, "name": app.name, "environment": app.environment, "mode": app.mode, "purpose": app.purpose,
                           "authorized_scope": app.authorized_scope}
    data["overview"] = svc.overview(s, app)
    data["findings"] = [svc.finding_json(f, s, detail=True) for f in s.scalars(select(Finding).where(Finding.application_id == app.id).order_by(Finding.updated_at.desc()))]
    data["assessments"] = [svc.assessment_json(a, s) for a in s.scalars(select(Assessment).where(Assessment.application_id == app.id).order_by(Assessment.created_at.desc()).limit(10))]
    with platform_session() as p:
        names = {u.id: u.username for u in p.scalars(select(User))}
        data["assignees"] = [{"user": names.get(a.staff_user_id), "duty": a.duty}
                             for a in p.scalars(select(CaseAssignment).where(CaseAssignment.case_id == case.id, CaseAssignment.active.is_(True)))]
    return data


@router.get("/cases/{case_id}")
def get_case(case_id: str, caller: Caller = StaffCaller):
    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        bundle = _case_bundle(s, case)
        bundle["your_duty"] = a.duty
        return bundle


@router.get("/cases/{case_id}/investigation")
def investigation(case_id: str, caller: Caller = StaffCaller):
    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        release = svc.latest_release(s, app.id)
        edges = [{"id": e.id, "test_id": e.test_id, "component_id": e.component_id, "status": e.status, "source": e.source,
                  "rationale": e.rationale, "reviewer": e.reviewer, "revision": e.revision, "updated_at": svc.ts(e.updated_at)}
                 for e in s.scalars(select(DependencyEdge).where(DependencyEdge.application_id == app.id).order_by(DependencyEdge.test_id, DependencyEdge.component_id))]
        mapped = {e["component_id"] for e in edges if e["status"] == "accepted"}
        change = s.scalars(select(ChangeSet).where(ChangeSet.application_id == app.id).order_by(ChangeSet.created_at.desc())).first()
        return {
            "case": {"id": case.id, "title": case.title, "state": case.state},
            "release": svc.release_json(release) if release else None,
            "coverage_contract": svc.contract(s, app.id),
            "edges": edges,
            "unmapped_components": sorted(set(release.manifest["components"]) - mapped) if release else [],
            "change": svc.change_json(change) if change else None,
            "tests": (try_for_application(s, app.id) or {"tests": []})["tests"],
            "profile": svc.onboarding_status(s, app, try_for_application(s, app.id)),
            "connection": svc.connection_json(s, app),
            "your_duty": a.duty,
        }


class EdgeReviewIn(BaseModel):
    test_id: str
    component_id: str
    action: str = Field(pattern=r"^(propose|accept|reject)$")
    rationale: str = Field(min_length=3)
    expected_revision: int | None = None


@router.post("/cases/{case_id}/coverage-reviews")
def coverage_review(case_id: str, body: EdgeReviewIn, caller: Caller = StaffCaller):
    """Propose, accept or reject a dependency edge; a proposer cannot accept their own proposal."""
    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        if body.test_id not in (try_for_application(s, case.application_id) or {"tests_by_id": {}})["tests_by_id"]:
            raise api_error(422, "unknown_test", "test is not in this application's active profile")
        edge = s.scalars(select(DependencyEdge).where(DependencyEdge.application_id == case.application_id, DependencyEdge.test_id == body.test_id,
                                                      DependencyEdge.component_id == body.component_id).with_for_update()).first()
        if body.action == "propose":
            release = svc.latest_release(s, case.application_id)
            if release is None or body.component_id not in release.manifest["components"]:
                raise api_error(422, "unknown_component", "component is not in the current release manifest")
            if edge and edge.status != "rejected":
                raise api_error(409, "exists", f"edge already {edge.status}")
            if edge:
                edge.status, edge.source, edge.rationale, edge.reviewer, edge.revision, edge.updated_at = "proposed", "analyst", body.rationale, caller.username, edge.revision + 1, time.time()
            else:
                edge = DependencyEdge(workspace_id=a.workspace_id, application_id=case.application_id, test_id=body.test_id, component_id=body.component_id,
                                      status="proposed", source="analyst", rationale=body.rationale, reviewer=caller.username)
                s.add(edge)
        else:
            if edge is None:
                raise api_error(404, "not_found", "edge not found")
            if body.expected_revision is not None and edge.revision != body.expected_revision:
                raise api_error(409, "stale_revision", "edge changed since you loaded it")
            if body.action == "accept" and edge.status == "proposed" and edge.reviewer == caller.username:
                raise api_error(403, "separation_of_duties", "another reviewer must accept your proposal")
            edge.status = "accepted" if body.action == "accept" else "rejected"
            edge.rationale, edge.reviewer, edge.revision, edge.updated_at = body.rationale, caller.username, edge.revision + 1, time.time()
        audit(s, a.workspace_id, caller, f"edge.{body.action}", f"{body.test_id}->{body.component_id}", {"rationale": body.rationale})
        return {"test_id": edge.test_id, "component_id": edge.component_id, "status": edge.status, "revision": edge.revision}


class RequestIn(BaseModel):
    body: str = Field(min_length=3)


@router.post("/cases/{case_id}/evidence-requests", status_code=201)
def request_evidence(case_id: str, body: RequestIn, caller: Caller = StaffCaller):
    a = assignment(caller, case_id, "analyst", "reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        s.add(EvidenceRequest(workspace_id=a.workspace_id, case_id=case_id, requested_by=caller.username, body=body.body))
        if case.state in ("assessment", "reassessment"):
            cases.transition(s, case, "awaiting_customer")
        audit(s, a.workspace_id, caller, "case.evidence_request", case_id)
        return {"ok": True, "state": case.state}


class StaffMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    visibility: str = Field(pattern=r"^(internal|customer)$")


@router.post("/cases/{case_id}/messages", status_code=201)
def staff_message(case_id: str, body: StaffMessageIn, caller: Caller = StaffCaller):
    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        s.add(CaseMessage(workspace_id=a.workspace_id, case_id=case_id, author=caller.username, author_kind="staff", visibility=body.visibility, body=body.body))
        from assureops_domain import notices

        return {"ok": True, "notified": notices.case_message(s, s.get(AssessmentCase, case_id), author=caller.username, author_kind="staff",
                                                             visibility=body.visibility, body=body.body)}


@router.get("/cases/{case_id}/evidence/{run_id}")
def case_evidence(case_id: str, run_id: str, caller: Caller = StaffCaller):
    """Raw evidence through the case-scoped grant only."""
    a = assignment(caller, case_id, "analyst", "reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        run = s.get(TestRun, run_id)
        if run is None or run.application_id != case.application_id:
            raise api_error(404, "not_found", "evidence not found")
        audit(s, a.workspace_id, caller, "evidence.read", run.id)
        return svc.evidence_json(run, s, with_record=True)


class EvidenceReviewIn(BaseModel):
    run_id: str
    decision: str = Field(pattern=r"^(accept|reject)$")
    note: str = Field(min_length=3)


@router.post("/cases/{case_id}/evidence-reviews", status_code=201)
def review_evidence(case_id: str, body: EvidenceReviewIn, caller: Caller = StaffCaller):
    a = assignment(caller, case_id, "analyst", "reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        run = s.get(TestRun, body.run_id)
        if run is None or run.application_id != case.application_id:
            raise api_error(404, "not_found", "evidence not found")
        if s.get(Assessment, run.assessment_id).requested_by == caller.username:
            raise api_error(403, "separation_of_duties", "you requested this assessment; another reviewer must confirm its evidence")
        s.add(EvidenceReview(workspace_id=a.workspace_id, run_id=run.id, reviewer=caller.username, decision=body.decision, note=body.note))
        audit(s, a.workspace_id, caller, f"evidence.{body.decision}", run.id)
        return {"ok": True}


class FindingDecisionIn(BaseModel):
    decision: str = Field(pattern=r"^(confirm|erroneous)$")
    note: str = Field(min_length=3)
    expected_revision: int


@router.post("/cases/{case_id}/findings/{finding_id}/reviews")
def decide_finding(case_id: str, finding_id: str, body: FindingDecisionIn, caller: Caller = StaffCaller):
    """Confirm a disputed finding or record an audited determination that it was erroneous."""
    a = assignment(caller, case_id, "reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        f = s.scalars(select(Finding).where(Finding.id == finding_id).with_for_update()).first()
        if f is None or f.application_id != case.application_id:
            raise api_error(404, "not_found", "finding not found in this case")
        if f.revision != body.expected_revision:
            raise api_error(409, "stale_revision", "the finding changed since you loaded it")
        s.add(FindingReview(workspace_id=a.workspace_id, finding_id=f.id, reviewer=caller.username, reviewer_kind="staff",
                            decision=body.decision, note=body.note, finding_revision=f.revision))
        if body.decision == "erroneous":
            f.state, f.resolution = "resolved", {"by": "reviewer_determination", "reviewer": caller.username, "note": body.note, "at": time.time()}
        else:
            f.state = "open"
        f.revision += 1
        f.updated_at = time.time()
        audit(s, a.workspace_id, caller, f"finding.{body.decision}", f.id)
        return svc.finding_json(f, s, detail=True)


class StaffAssessmentIn(BaseModel):
    scope: str = Field(pattern=r"^(full|retest)$")


@router.post("/cases/{case_id}/assessments", status_code=202)
def staff_assessment(case_id: str, body: StaffAssessmentIn, caller: Caller = StaffCaller, idempotency_key: str | None = Header(default=None)):
    a = assignment(caller, case_id, "analyst")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        release = svc.latest_release(s, app.id)
        if release is None:
            raise api_error(409, "no_release", "the customer has not submitted a release")
        job = svc.create_assessment(s, app, release, body.scope, caller.username, case_id=case.id, idempotency_key=idempotency_key)
        if case.state == "reassessment":
            cases.transition(s, case, "assessment")
        audit(s, a.workspace_id, caller, "assessment.create", job.id, {"scope": body.scope})
        return {"id": job.id, "tests": job.plan["tests"]}


# ---------------- Reports and publication ----------------

@router.post("/cases/{case_id}/reports", status_code=201)
def draft_report(case_id: str, caller: Caller = StaffCaller):
    a = assignment(caller, case_id, "analyst")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        release = svc.latest_release(s, app.id)
        if release is None:
            raise api_error(409, "no_release", "nothing to report on")
        if s.scalars(select(Assessment).where(Assessment.application_id == app.id, Assessment.status.in_(["queued", "running"]))).first():
            raise api_error(409, "assessment_running", "wait for the running assessment to finish for a consistent snapshot")
        snapshot = svc.build_snapshot(s, app, release, case)
        report = Report(workspace_id=a.workspace_id, application_id=app.id, case_id=case.id, release_id=release.id, snapshot=snapshot,
                        sha256=canonical_hash(snapshot), drafted_by=caller.username)
        for old in s.scalars(select(Report).where(Report.case_id == case.id, Report.state == "draft")):
            old.state = "superseded"
        s.add(report)
        s.flush()
        cases.transition(s, case, "awaiting_review")
        audit(s, a.workspace_id, caller, "report.draft", report.id, {"sha256": report.sha256})
        return {"id": report.id, "sha256": report.sha256}


@router.get("/cases/{case_id}/reports/{report_id}")
def get_report(case_id: str, report_id: str, caller: Caller = StaffCaller):
    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        report = s.get(Report, report_id)
        if report is None or report.case_id != case_id:
            raise api_error(404, "not_found", "report not found")
        data = svc.report_json(report, s, svc.get_application(s, report.application_id))
        data["explanations"] = svc.explanations(s, report.id, accepted_only=False)
        data["decisions"] = [{"reviewer": d.reviewer, "decision": d.decision, "reason": d.reason, "at": svc.ts(d.created_at)}
                             for d in s.scalars(select(ReviewDecision).where(ReviewDecision.report_id == report.id).order_by(ReviewDecision.created_at))]
        return data


class ReviewIn(BaseModel):
    report_id: str
    decision: str = Field(pattern=r"^(publish|return)$")
    reason: str = Field(min_length=3)
    expected_revision: int


@router.post("/cases/{case_id}/reviews")
def review_report(case_id: str, body: ReviewIn, caller: Caller = StaffCaller):
    """Independent review: the drafter cannot publish, and the snapshot must still describe the current release."""
    a = assignment(caller, case_id, "reviewer")
    caller.require_staff("senior_reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        report = s.scalars(select(Report).where(Report.id == body.report_id).with_for_update()).first()
        if report is None or report.case_id != case_id:
            raise api_error(404, "not_found", "report not found")
        if report.revision != body.expected_revision or report.state != "draft":
            raise api_error(409, "stale_revision", "this report changed or was already decided; reload it")
        if report.drafted_by == caller.username:
            raise api_error(403, "separation_of_duties", "you drafted this report; another reviewer must decide")
        if body.decision == "publish":
            drift = svc.publication_drift(s, report)
            if drift:
                raise api_error(409, "snapshot_stale", "cannot publish: " + "; ".join(drift) + ". The analyst must draft a new snapshot.")
        s.add(ReviewDecision(workspace_id=a.workspace_id, report_id=report.id, reviewer=caller.username, decision=body.decision,
                             reason=body.reason, report_revision=report.revision))
        report.revision += 1
        if body.decision == "return":
            report.state = "returned"
            cases.transition(s, case, "assessment")
        else:
            report.state = "published"
            for pub in s.scalars(select(ReportPublication).where(ReportPublication.application_id == report.application_id, ReportPublication.state == "published")):
                pub.state = "superseded"
                prior = s.get(Report, pub.report_id)
                prior.state = "superseded"
            s.add(ReportPublication(workspace_id=a.workspace_id, report_id=report.id, application_id=report.application_id, case_id=case.id,
                                    release=report.snapshot["release"]["version"], sha256=report.sha256, published_by=caller.username))
            cases.transition(s, case, "published")
            cases.transition(s, case, "monitoring")
        audit(s, a.workspace_id, caller, f"report.{body.decision}", report.id, {"reason": body.reason})
        return {"report_id": report.id, "state": report.state, "case_state": case.state}


# ---------------- Incidents ----------------

@router.get("/incidents")
def incidents(caller: Caller = StaffCaller):
    with platform_session() as p:
        mine = p.scalars(select(CaseAssignment).where(CaseAssignment.staff_user_id == caller.user_id, CaseAssignment.active.is_(True))).all()
    out = []
    for a in mine:
        with tenant_session(a.workspace_id) as s:
            case = s.get(AssessmentCase, a.case_id)
            for i in s.scalars(select(Incident).where(Incident.application_id == case.application_id).order_by(Incident.created_at.desc())):
                out.append({"id": i.id, "case_id": case.id, "case_title": case.title, "control": i.control_id, "severity": i.severity, "title": i.title,
                            "state": i.state, "revision": i.revision, "cohort": i.cohort, "closure": i.closure, "created_at": svc.ts(i.created_at),
                            "your_duty": a.duty})
    return sorted({i["id"]: i for i in out}.values(), key=lambda i: i["created_at"], reverse=True)


class CloseIn(BaseModel):
    case_id: str
    note: str = Field(min_length=3)
    expected_revision: int


@router.post("/incidents/{incident_id}/close")
def close(incident_id: str, body: CloseIn, caller: Caller = StaffCaller):
    a = assignment(caller, body.case_id, "reviewer")
    caller.require_staff("senior_reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, body.case_id)
        incident = s.scalars(select(Incident).where(Incident.id == incident_id).with_for_update()).first()
        if incident is None or case is None or incident.application_id != case.application_id:
            raise api_error(404, "not_found", "incident not found in this case")
        release = svc.latest_release(s, incident.application_id)
        try:
            closure = close_incident(s, incident, expected_revision=body.expected_revision, reviewer=caller.username, note=body.note,
                                     state=reducer.readiness(s, incident.application_id, release, svc.app_profile(s, incident.application_id)))
        except FindingError as exc:
            raise api_error(409, exc.code, exc.detail)
        s.flush()
        after = reducer.readiness(s, incident.application_id, release, svc.app_profile(s, incident.application_id))
        cases.sync_index(s, case, blockers=len(after["gate"]["blocking"]))  # queue metadata follows the reviewed closure
        audit(s, a.workspace_id, caller, "incident.close", incident.id, closure)
        return {"id": incident.id, "state": incident.state, "closure": closure}


# ---------------- Operations and governance ----------------

@router.get("/operations")
def operations(caller: Caller = StaffCaller):
    """Platform health only: counts and ages, never customer content."""
    caller.require_staff("operator", "case_manager", "analyst", "senior_reviewer")
    now = time.time()
    with platform_session() as p:
        pending = p.scalar(select(func.count()).select_from(Outbox).where(Outbox.dispatched_at.is_(None))) or 0
        oldest = p.scalar(select(func.min(Outbox.created_at)).where(Outbox.dispatched_at.is_(None)))
        workspaces = [row.workspace_id for row in p.scalars(select(CaseIndex))]
    steps = {"pending": 0, "running": 0, "expired_leases": 0, "failed": 0}
    jobs = {"queued": 0, "running": 0, "failed_last_day": 0}
    events_last_5m = 0
    for ws in sorted(set(workspaces)):
        with tenant_session(ws) as s:
            for st in s.scalars(select(JobStep).where(JobStep.status.in_(["pending", "running", "failed"]))):
                steps[st.status] += 1
                if st.status == "running" and (st.lease_expires_at or 0) < now:
                    steps["expired_leases"] += 1
            for job in s.scalars(select(Assessment).where(Assessment.created_at > now - 86400)):
                if job.status in jobs:
                    jobs[job.status] += 1
                if job.status == "failed":
                    jobs["failed_last_day"] += 1
            events_last_5m += s.scalar(select(func.count()).select_from(RuntimeEvent).where(RuntimeEvent.received_at > now - 300)) or 0
    return {
        "outbox": {"pending": pending, "oldest_age_seconds": round(now - oldest) if oldest else 0},
        "steps": steps, "jobs": jobs, "ingestion": {"events_last_5_minutes": events_last_5m},
        "inference": ai_routes.operations_summary(),
        "runner": {"isolation": f"disposable {settings().runner_mode} per step", "environment": "scrubbed: no database, broker, storage or platform keys",
                   "egress": "pinned to the connection origin; redirects refused; private targets only when ALLOW_PRIVATE_TARGETS is set",
                   "allow_private_targets": settings().allow_private_targets},
    }


@router.get("/governance")
def governance(caller: Caller = StaffCaller):
    with platform_session() as p:
        staff = [{"user": u.username, "name": u.display_name, "roles": sorted(r.role for r in p.scalars(select(StaffRole).where(StaffRole.user_id == u.id, StaffRole.active.is_(True))))}
                 for u in p.scalars(select(User).where(User.kind == "staff"))]
        qualifications = [{"phase": q.phase, "provider": q.provider, "model": q.model, "status": q.status, "dataset": q.dataset,
                           "metrics": q.metrics, "recorded_by": q.recorded_by, "at": q.created_at}
                          for q in p.scalars(select(ModelQualification).order_by(ModelQualification.created_at.desc()))]
    from .auth import staff_mfa_required

    return {
        "profile": {"version": control_catalog()["catalog_id"] + "-" + control_catalog()["version"], "digest": canonical_hash(control_catalog())[:16],
                    "controls": control_catalog()["controls"], "gate_policy": {"version": "per application profile", "blocking_severities": ["critical", "high"],
                                    # the reducer's incomplete rule: evidence not current, or results not yet decided
                                    "incomplete_when": ["stale", "unavailable", "unverified", "review_required"]},
                    "tests": [], "requirements": {}, "note": "Tests, gates and requirements are defined per application profile revision."},
        "model_routes": ai_routes.route_table(None), "qualification_records": qualifications,
        "staff_permissions": staff,
        "identity": {"provider": "Keycloak (OIDC)",
                     "staff_mfa": "enforced: staff tokens must carry a one-time-password authentication" if staff_mfa_required()
                     else "not enforced (STAFF_MFA_REQUIRED=false)"},
    }


# ---------------- Application profile review ----------------

class StaffProfileIn(BaseModel):
    profile: dict


@router.post("/cases/{case_id}/profiles", status_code=201)
def staff_propose_profile(case_id: str, body: StaffProfileIn, caller: Caller = StaffCaller):
    a = assignment(caller, case_id, "analyst")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        try:
            row = connections.propose_profile(s, app, body.profile, source="analyst", actor=caller.username)
        except connections.OnboardingError as exc:
            raise api_error(422 if exc.code == "invalid_profile" else 409, exc.code, exc.detail)
        audit(s, a.workspace_id, caller, "profile.propose", app.id, {"revision": row.revision})
        return svc.profile_row_json(row)


@router.get("/cases/{case_id}/profiles")
def staff_profiles(case_id: str, caller: Caller = StaffCaller):
    from assureops_domain.models import ApplicationProfile

    a = assignment(caller, case_id)
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        return [svc.profile_row_json(r) for r in s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == case.application_id)
                                                          .order_by(ApplicationProfile.revision.desc()))]


class StaffProfileDecisionIn(BaseModel):
    revision: int
    decision: str = Field(pattern=r"^(activate|reject)$")
    note: str = Field(min_length=3)


@router.post("/cases/{case_id}/profile-reviews")
def staff_review_profile(case_id: str, body: StaffProfileDecisionIn, caller: Caller = StaffCaller):
    a = assignment(caller, case_id, "reviewer")
    caller.require_staff("senior_reviewer")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        try:
            row = (connections.activate_profile(s, app, body.revision, reviewer=caller.username, note=body.note) if body.decision == "activate"
                   else connections.reject_profile(s, app, body.revision, reviewer=caller.username, note=body.note))
        except connections.OnboardingError as exc:
            raise api_error(403 if exc.code == "separation_of_duties" else 409, exc.code, exc.detail)
        except ProfileError as exc:
            raise api_error(422, exc.code, exc.detail)
        audit(s, a.workspace_id, caller, f"profile.{body.decision}", app.id, {"revision": body.revision})
        return svc.profile_row_json(row)
