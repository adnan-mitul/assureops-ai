"""Public inquiries, staff conversion into workspaces, invitations, member grants/revocation."""

import os
import re
import time

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases, grants, handoffs
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Inquiry, Invitation, Membership, StaffRole, User, Workspace

from .auth import Caller, CustomerCaller, StaffCaller, _verify, api_error
from assureops_domain.config import settings

router = APIRouter(prefix="/v1", tags=["handoffs"])
PORTAL = os.environ.get("PUBLIC_CUSTOMER_ORIGIN", "http://localhost:3700")  # invitation links point here; set the public address when hosted


def _err(exc: handoffs.HandoffError):
    return api_error({"not_found": 404, "wrong_account": 403, "self_grant": 403, "last_owner": 409, "last_admin": 409,
                      "already_invited": 409}.get(exc.code, 422), exc.code, exc.detail)


# ---------------- Public inquiry -> staff conversion ----------------

class InquiryIn(BaseModel):
    company: str = Field(min_length=2, max_length=120)
    contact_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    message: str = Field(min_length=10, max_length=4000)


@router.post("/public/inquiries", status_code=201)
def submit_inquiry(body: InquiryIn, request: Request):
    from .ratelimit import check

    check("inquiry", request.client.host if request.client else "unknown", limit=5, window_seconds=3600)
    with platform_session() as s:
        inq = Inquiry(company=body.company, contact_email=body.contact_email.lower(), message=body.message)
        s.add(inq)
        s.flush()
        for manager in s.scalars(select(User).join(StaffRole, StaffRole.user_id == User.id).where(StaffRole.role == "case_manager")):
            handoffs.notify(s, recipient=manager.username, kind="inquiry", subject=f"New inquiry from {body.company}",
                            body=f"{body.company} ({body.contact_email}) wrote:\n\n{body.message}\n")
        return {"id": inq.id, "status": inq.status}


@router.get("/staff/inquiries")
def list_inquiries(caller: Caller = StaffCaller):
    caller.require_staff("case_manager", "admin")
    with platform_session() as s:
        return [{"id": i.id, "company": i.company, "contact_email": i.contact_email, "message": i.message, "status": i.status,
                 "workspace_id": i.workspace_id, "created_at": i.created_at} for i in s.scalars(select(Inquiry).order_by(Inquiry.created_at.desc()))]


class ConvertIn(BaseModel):
    workspace_id: str = Field(pattern=r"^[a-z0-9-]{3,40}$")
    workspace_name: str = Field(min_length=2, max_length=120)


@router.post("/staff/inquiries/{inquiry_id}/convert", status_code=201)
def convert_inquiry(inquiry_id: str, body: ConvertIn, caller: Caller = StaffCaller):
    """Creates the workspace and invites the contact as its owner; no staff access to tenant data is granted by this."""
    caller.require_staff("case_manager", "admin")
    with platform_session() as s:
        inq = s.scalars(select(Inquiry).where(Inquiry.id == inquiry_id).with_for_update()).first()
        if inq is None or inq.status != "new":
            raise api_error(409, "invalid_state", "inquiry not found or already decided")
        if s.get(Workspace, body.workspace_id):
            raise api_error(409, "exists", "workspace id already used")
        s.add(Workspace(id=body.workspace_id, name=body.workspace_name))
        s.flush()
        invitation, _ = handoffs.invite(s, workspace_id=body.workspace_id, email=inq.contact_email, role="owner", invited_by=caller.username,
                                        portal_origin=PORTAL)
        inq.status, inq.workspace_id, inq.decided_by = "converted", body.workspace_id, caller.username
    with tenant_session(body.workspace_id) as s:
        cases.audit(s, workspace_id=body.workspace_id, actor=caller.username, actor_kind="staff", action="workspace.create_from_inquiry",
                    target=inquiry_id)
    return {"workspace_id": body.workspace_id, "invitation_id": invitation.id, "owner_email": inq.contact_email}


# ---------------- Invitations ----------------

class InviteIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    role: str = Field(pattern=r"^(owner|developer|reviewer|viewer)$")


@router.post("/invitations", status_code=201)
def create_invitation(body: InviteIn, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with platform_session() as s:
        try:
            inv, _ = handoffs.invite(s, workspace_id=caller.workspace_id, email=body.email, role=body.role, invited_by=caller.username, portal_origin=PORTAL)
        except handoffs.HandoffError as exc:
            raise _err(exc)
        s.flush()  # assign the id before answering, so the owner can revoke this invitation
        result = {"id": inv.id, "email": inv.email, "role": inv.role, "expires_at": inv.expires_at}
    with tenant_session(caller.workspace_id) as s:
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="invitation.create",
                    target=body.email, detail={"role": body.role})
    return result


@router.get("/invitations")
def list_invitations(caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with platform_session() as s:
        return [{"id": i.id, "email": i.email, "role": i.role, "invited_by": i.invited_by, "expires_at": i.expires_at,
                 "accepted_at": i.accepted_at, "revoked_at": i.revoked_at}
                for i in s.scalars(select(Invitation).where(Invitation.workspace_id == caller.workspace_id).order_by(Invitation.created_at.desc()))]


@router.post("/invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with platform_session() as s:
        inv = s.get(Invitation, invitation_id)
        if inv is None or inv.workspace_id != caller.workspace_id:
            raise api_error(404, "not_found", "invitation not found")
        if inv.accepted_at is None and inv.revoked_at is None:
            from assureops_domain.models import now

            inv.revoked_at = now()
        return {"id": inv.id, "revoked": inv.revoked_at is not None}


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=100)


@router.post("/invitations/accept")
def accept_invitation(body: AcceptIn, authorization: str | None = Header(default=None)):
    """Signed-in customer identity (it may not belong to any workspace yet) accepts an invitation addressed to it."""
    claims = _verify(authorization, settings().customer_audience, settings().customer_issuer)
    username = claims.get("preferred_username") or claims.get("email")
    if not username or not re.match(r"^[^@\s]+@[^@\s]+$", username):
        raise api_error(403, "no_email", "your account has no verified e-mail address")
    with platform_session() as s:
        try:
            m = handoffs.accept(s, token=body.token, username=username, display_name=claims.get("name") or username)
        except handoffs.HandoffError as exc:
            raise _err(exc)
        result = {"workspace_id": m.workspace_id, "role": m.role}
    with tenant_session(result["workspace_id"]) as s:
        cases.audit(s, workspace_id=result["workspace_id"], actor=username, actor_kind="customer", action="invitation.accept", target=username)
    return result


# ---------------- Member grants and revocation ----------------

class RoleIn(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(owner|developer|reviewer|viewer)$")


@router.put("/members/{username}")
def change_member(username: str, body: RoleIn, caller: Caller = CustomerCaller):
    """Owner grants a role, or revokes access with role null. Revocation takes effect on the member's next request."""
    caller.require_role("owner")
    with platform_session() as s:
        try:
            m = handoffs.set_role(s, workspace_id=caller.workspace_id, username=username, role=body.role, actor=caller.username)
        except handoffs.HandoffError as exc:
            raise _err(exc)
        result = {"user": username, "role": m.role, "active": m.active}
    ended = 0
    with tenant_session(caller.workspace_id) as s, platform_session() as p:
        if body.role != "developer":  # assignments belong to developers; removal or another role ends them
            from assureops_domain.models import ApplicationGrant

            user = p.scalars(select(User).where(User.username == username)).first()
            for g in s.scalars(select(ApplicationGrant).where(ApplicationGrant.user_id == (user.id if user else ""), ApplicationGrant.revoked_at.is_(None))):
                g.revoked_at, g.revoked_by = time.time(), caller.username
                ended += 1
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer",
                    action="member.revoke" if body.role is None else "member.grant", target=username, detail={"role": body.role, "assignments_ended": ended})
    return {**result, "assignments_ended": ended}


# ---------------- Application-scoped developer assignment ----------------

class AssignmentIn(BaseModel):
    expires_at: float | None = None


@router.get("/applications/{application_id}/developers")
def list_application_developers(application_id: str, caller: Caller = CustomerCaller):
    from . import services as svc

    with tenant_session(caller.workspace_id) as s, platform_session() as p:
        svc.get_application(s, application_id)
        return grants.application_developers(s, p, application_id)


@router.put("/applications/{application_id}/developers/{username}")
def assign_application_developer(application_id: str, username: str, body: AssignmentIn | None = None, caller: Caller = CustomerCaller):
    """Owner assigns a workspace developer to one application; the developer may then change only that application."""
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s, platform_session() as p:
        try:
            g = grants.assign_developer(s, p, workspace_id=caller.workspace_id, application_id=application_id, username=username.lower(),
                                        actor=caller.username, expires_at=(body.expires_at if body else None))
        except handoffs.HandoffError as exc:
            raise _err(exc)
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="application.assign",
                    target=application_id, detail={"developer": username.lower(), "expires_at": g.expires_at})
        return {"application_id": application_id, "user": username.lower(), "expires_at": g.expires_at, "active": True}


@router.delete("/applications/{application_id}/developers/{username}")
def unassign_application_developer(application_id: str, username: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s, platform_session() as p:
        removed = grants.unassign_developer(s, p, workspace_id=caller.workspace_id, application_id=application_id, username=username.lower(),
                                            actor=caller.username)
        if not removed:
            raise api_error(404, "not_found", "no active assignment for that developer")
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="application.unassign",
                    target=application_id, detail={"developer": username.lower()})
        return {"application_id": application_id, "user": username.lower(), "active": False}
