"""AI phase surface: route status, data policy, approved sources, phase requests and proposal review."""

import hashlib

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import AiResult, Incident, Release, Report, SourceDocument, Workspace

from . import services as svc
from .access import require_application_writer
from .auth import Caller, CustomerCaller, api_error

router = APIRouter(prefix="/v1", tags=["ai"])


def route_table(workspace) -> list[dict]:
    from assureops_ai import service

    return service.route_table(workspace)


def operations_summary() -> dict:
    from assureops_ai import service

    return service.operations_summary()


@router.get("/ai/phases")
def phases(caller: Caller = CustomerCaller):
    with platform_session() as s:
        ws = s.get(Workspace, caller.workspace_id)
        return {"external_processing": bool(ws.external_processing), "phases": route_table(ws)}


class DataPolicyIn(BaseModel):
    external_processing: bool
    reason: str = Field(min_length=5)


@router.put("/workspace/data-policy")
def set_data_policy(body: DataPolicyIn, caller: Caller = CustomerCaller):
    """Owner decision. External processing applies only to phases approved for an external provider."""
    caller.require_role("owner")
    with platform_session() as s:
        ws = s.get(Workspace, caller.workspace_id)
        ws.external_processing = body.external_processing
    with tenant_session(caller.workspace_id) as s:
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="data_policy.set",
                    target=caller.workspace_id, detail={"external_processing": body.external_processing, "reason": body.reason})
    return {"external_processing": body.external_processing}


# ---------------- Approved reference sources ----------------

class SourceIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    kind: str = Field(pattern=r"^(policy|requirement|design|runbook|other)$")
    text: str = Field(min_length=20, max_length=200_000)


@router.post("/applications/{application_id}/sources", status_code=201)
def add_source(application_id: str, body: SourceIn, caller: Caller = CustomerCaller):
    caller.require_role("owner", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        row = SourceDocument(workspace_id=app.workspace_id, application_id=app.id, title=body.title, kind=body.kind, text=body.text,
                             sha256=hashlib.sha256(body.text.encode()).hexdigest(), approved_by=caller.username)
        s.add(row)
        s.flush()
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="source.approve", target=row.id)
        return {"id": row.id, "title": row.title, "sha256": row.sha256}


@router.get("/applications/{application_id}/sources")
def list_sources(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [{"id": d.id, "title": d.title, "kind": d.kind, "sha256": d.sha256[:16], "approved_by": d.approved_by, "chars": len(d.text),
                 "created_at": d.created_at} for d in s.scalars(select(SourceDocument).where(SourceDocument.application_id == application_id))]


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=5, ge=1, le=20)


@router.post("/applications/{application_id}/sources/search")
def search_sources(application_id: str, body: SearchIn, caller: Caller = CustomerCaller):
    from assureops_ai import retrieval

    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        docs = s.scalars(select(SourceDocument).where(SourceDocument.application_id == application_id)).all()
        method, hits = retrieval.hybrid_search([{"id": d.id, "title": d.title, "text": d.text} for d in docs], body.query, body.k)
        return {"method": method,
                "results": [{"score": score, "source_id": c.source_id, "title": c.title, "start": c.start, "text": c.text[:600]}
                            for score, c in hits]}


# ---------------- Phase requests ----------------

class PhaseIn(BaseModel):
    run_id: str | None = None
    claims: list[str] | None = Field(default=None, max_length=4)
    texts: list[str] | None = Field(default=None, max_length=10)
    release_id: str | None = None
    report_id: str | None = None
    incident_id: str | None = None
    source_ids: list[str] | None = None
    query: str | None = Field(default=None, max_length=300)


@router.post("/applications/{application_id}/ai/{phase}", status_code=202)
def request_phase(application_id: str, phase: str, body: PhaseIn, caller: Caller = CustomerCaller):
    from assureops_ai import service

    caller.require_role("owner", "developer", "reviewer")
    from .ratelimit import check

    check("ai_phase", caller.workspace_id, limit=60, window_seconds=3600)
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id, "reviewer")
        refs = {k: v for k, v in body.model_dump().items() if v is not None}
        phase = phase.upper()
        if phase == "B":
            release = s.get(Release, refs.get("release_id")) if refs.get("release_id") else svc.latest_release(s, app.id)
            if release is None or release.application_id != app.id:
                raise api_error(409, "no_release", "phase B needs a collected release")
            refs["release_id"] = release.id
        if phase == "F":
            report = s.get(Report, refs.get("report_id") or "")
            if report is None or report.application_id != app.id or report.state not in ("published", "superseded"):
                raise api_error(404, "not_found", "phase F explains a published report snapshot")
        if phase == "D":
            from assureops_domain.models import TestRun

            run = s.get(TestRun, refs.get("run_id") or "")
            if run is None or run.application_id != app.id:
                raise api_error(404, "not_found", "phase D scores one recorded test run")
        if phase == "E":
            incident = s.get(Incident, refs.get("incident_id") or "")
            if incident is None or incident.application_id != app.id:
                raise api_error(404, "not_found", "incident not found")
        try:
            row = service.request(s, app, phase, refs, caller.username)
        except service.AiError as exc:
            raise api_error(429 if exc.code == "queue_full" else 422, exc.code, exc.detail)
        return service.result_json(row)


@router.post("/applications/{application_id}/profiles/ai-plan", status_code=201)
def build_ai_plan(application_id: str, caller: Caller = CustomerCaller):
    """Assemble one proposed profile revision from this application's accepted phase A and C proposals; another person activates it."""
    from assureops_ai import plan, service
    from assureops_domain import connections

    caller.require_role("owner", "developer")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        try:
            row, summary = plan.assemble(s, app, actor=caller.username)
        except service.AiError as exc:
            raise api_error(409, exc.code, exc.detail)
        except connections.OnboardingError as exc:
            raise api_error(422, exc.code, exc.detail)
        return {**svc.profile_row_json(row), "plan": summary}


@router.get("/applications/{application_id}/ai/results")
def list_results(application_id: str, caller: Caller = CustomerCaller):
    from assureops_ai import service

    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        return [service.result_json(r) for r in s.scalars(select(AiResult).where(AiResult.application_id == application_id, AiResult.shadow_of.is_(None))
                                                         .order_by(AiResult.created_at.desc()).limit(50))]


class AiReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(accept|reject)$")
    note: str = Field(min_length=3)


@router.post("/ai/results/{result_id}/review")
def review_result(result_id: str, body: AiReviewIn, caller: Caller = CustomerCaller):
    from assureops_ai import service

    caller.require_role("owner", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        row = s.scalars(select(AiResult).where(AiResult.id == result_id).with_for_update()).first()
        if row is None:
            raise api_error(404, "not_found", "result not found")
        try:
            effects = service.review(s, row, decision=body.decision, reviewer=caller.username, note=body.note)
        except service.AiError as exc:
            raise api_error(403 if exc.code == "separation_of_duties" else 409, exc.code, exc.detail)
        return {**service.result_json(row), "effects": effects}


@router.post("/ai/results/{result_id}/cancel")
def cancel_result(result_id: str, caller: Caller = CustomerCaller):
    from assureops_ai import service

    with tenant_session(caller.workspace_id) as s:
        row = s.scalars(select(AiResult).where(AiResult.id == result_id).with_for_update()).first()
        if row is None:
            raise api_error(404, "not_found", "result not found")
        require_application_writer(s, caller, row.application_id, "reviewer")
        cancelled = service.cancel(s, row, actor=caller.username)
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="ai.cancel", target=row.id,
                    detail={"phase": row.phase, "cancelled": cancelled})
        return {**service.result_json(row), "cancelled": cancelled}
