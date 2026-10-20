"""Risk acceptance surface: propose (assigned developer or owner), decide (a different owner or reviewer), revoke (owner)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases, reducer, risk
from assureops_domain.db import tenant_session
from assureops_domain.models import RiskAcceptance

from . import services as svc
from .access import require_application_writer
from .auth import Caller, CustomerCaller, api_error

router = APIRouter(prefix="/v1", tags=["risk"])


def _err(exc: risk.RiskError):
    return api_error({"separation_of_duties": 403, "already_decided": 409, "expired": 409}.get(exc.code, 422), exc.code, exc.detail)


def _audit(s, caller: Caller, action: str, target: str, detail: dict | None = None):
    cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action=action, target=target, detail=detail)


@router.get("/applications/{application_id}/risk-acceptances")
def list_acceptances(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        p = svc.app_profile(s, app.id)
        rows = s.scalars(select(RiskAcceptance).where(RiskAcceptance.application_id == app.id).order_by(RiskAcceptance.created_at.desc())).all()
        latest = svc.latest_release(s, app.id)
        return {"policy_max_severity": risk.allowed_severity(p), "max_days": risk.MAX_DAYS, "latest_release_id": latest.id if latest else None,
                "items": [{**risk.to_json(r), "applies_to_latest_release": bool(latest and r.release_id == latest.id)} for r in rows]}


class ProposeIn(BaseModel):
    control_id: str = Field(pattern=r"^C[0-9]{2}$")
    reason: str = Field(min_length=20, max_length=4000)
    compensating_controls: str = Field(min_length=10, max_length=4000)
    expires_in_days: int = Field(ge=1, le=risk.MAX_DAYS)


@router.post("/applications/{application_id}/risk-acceptances", status_code=201)
def propose(application_id: str, body: ProposeIn, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        release = svc.latest_release(s, app.id)
        if release is None:
            raise api_error(409, "no_release", "submit and assess a release first")
        state = reducer.readiness(s, app.id, release, svc.app_profile(s, app.id))
        control = next((c for c in state["controls"] if c["id"] == body.control_id), None)
        if control is None:
            raise api_error(404, "not_found", "control not in this application's profile")
        try:
            row = risk.propose(s, application_id=app.id, workspace_id=caller.workspace_id, release=release, control=control, reason=body.reason,
                               compensating=body.compensating_controls, days=body.expires_in_days, actor=caller.username)
        except risk.RiskError as exc:
            raise _err(exc)
        _audit(s, caller, "risk.propose", row.id, {"control": body.control_id, "release": release.version, "days": body.expires_in_days})
        return risk.to_json(row)


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(min_length=3, max_length=2000)


@router.post("/risk-acceptances/{acceptance_id}/decision")
def decide(acceptance_id: str, body: DecideIn, caller: Caller = CustomerCaller):
    caller.require_role("owner", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        row = s.scalars(select(RiskAcceptance).where(RiskAcceptance.id == acceptance_id).with_for_update()).first()
        if row is None:
            raise api_error(404, "not_found", "risk acceptance not found")
        if body.approve:  # recheck eligibility against current evidence and the reviewed profile at decision time
            p = svc.app_profile(s, row.application_id)
            latest = svc.latest_release(s, row.application_id)
            if latest is None or latest.id != row.release_id:
                raise api_error(409, "superseded", "a newer release exists; propose the acceptance for that release")
            state = reducer.readiness(s, row.application_id, latest, p)
            control = next((c for c in state["controls"] if c["id"] == row.control_id), {})
            ok, why = risk.eligible(control, p)
            if not ok:
                raise api_error(422, "not_acceptable", why)
        try:
            risk.decide(s, row, approve=body.approve, actor=caller.username, note=body.note)
        except risk.RiskError as exc:
            raise _err(exc)
        _audit(s, caller, "risk.approve" if body.approve else "risk.reject", row.id, {"control": row.control_id})
        return risk.to_json(row)


@router.post("/risk-acceptances/{acceptance_id}/revoke")
def revoke(acceptance_id: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        row = s.get(RiskAcceptance, acceptance_id)
        if row is None:
            raise api_error(404, "not_found", "risk acceptance not found")
        risk.revoke(row, actor=caller.username)
        _audit(s, caller, "risk.revoke", row.id, {"control": row.control_id})
        return risk.to_json(row)
