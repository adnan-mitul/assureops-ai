"""Machine surface: gateway action ledger, tool-server confirmation and runtime ingestion."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from assureops_domain import approvals, events
from assureops_domain.db import tenant_session
from assureops_domain.models import Application, EventSource, JobStep, LogicalAction

from .auth import Service, api_error, event_source, service

router = APIRouter(prefix="/v1", tags=["integration"])


def action_json(a: LogicalAction) -> dict:
    return {"action_id": a.id, "state": a.state, "approval_id": a.approval_id, "tool": a.tool, "result": a.result,
            "claim_revision": a.claim_revision, "origin": a.origin, "release": a.release}


def verified_origin(s, step_id: str | None) -> str:
    """Assessment traffic is recognised only for a step AssureOps is running right now."""
    if not step_id:
        return "live"
    step = s.get(JobStep, step_id)
    return "assessment" if step is not None and step.status == "running" else "live"


class ReserveIn(BaseModel):
    action_id: str = Field(min_length=8, max_length=80)
    approval_id: str | None = None
    approval_required: bool
    tool: str
    payload: dict
    tool_schema_hash: str
    permission_policy_version: str
    release: str
    requester: str
    assessment_step_id: str | None = None


@router.post("/integration/actions/reserve")
def reserve(body: ReserveIn, svc: Service = Depends(service("gateway"))):
    with tenant_session(svc.workspace_id) as s:
        app = s.get(Application, svc.application_id)
        origin = verified_origin(s, body.assessment_step_id)
        try:
            if body.approval_required:
                if not body.approval_id:
                    raise approvals.ApprovalError("approval_required", "a manager approval is required")
                action = approvals.reserve(s, approval_id=body.approval_id, action_id=body.action_id, application_id=app.id, environment=svc.environment,
                                           release=body.release, tool=body.tool, tool_schema_hash=body.tool_schema_hash, payload=body.payload,
                                           permission_policy_version=body.permission_policy_version, requester=body.requester)
            else:
                action = approvals.prepare_unapproved(s, workspace_id=svc.workspace_id, application_id=app.id, action_id=body.action_id,
                                                      tool=body.tool, payload=body.payload)
        except approvals.ApprovalError as exc:
            raise api_error(409, exc.code, exc.detail)
        if action.state == "reserved" and action.claim_revision == 1:
            action.origin, action.release = origin, body.release
        return action_json(action)


class TransitionIn(BaseModel):
    state: str
    result: dict | None = None


@router.post("/integration/actions/{action_id}/transition")
def transition(action_id: str, body: TransitionIn, svc: Service = Depends(service("gateway"))):
    with tenant_session(svc.workspace_id) as s:
        try:
            return action_json(approvals.transition(s, action_id, body.state, body.result))
        except approvals.ApprovalError as exc:
            raise api_error(409, exc.code, exc.detail)


@router.get("/integration/actions/{action_id}")
def get_action(action_id: str, svc: Service = Depends(service("gateway", "tool_server"))):
    with tenant_session(svc.workspace_id) as s:
        action = s.get(LogicalAction, action_id)
        if action is None or action.application_id != svc.application_id:
            raise api_error(404, "not_found", "action not registered")
        return action_json(action)


class EventBatch(BaseModel):
    events: list[dict] = Field(max_length=100)


@router.post("/runtime/events:batch")
def ingest(batch: EventBatch, source: EventSource = Depends(event_source)):
    """Per-event acceptance; accepted events are persisted before this returns."""
    with tenant_session(source.workspace_id) as s:
        return {"results": events.ingest(s, source, batch.events)}
