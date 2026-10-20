"""AssureOps admin surface: staff role grants/revocation and workload (metadata only, no customer content)."""

import time

from fastapi import APIRouter
from sqlalchemy import select

from assureops_domain import grants, handoffs
from assureops_domain.db import platform_session
from assureops_domain.models import CaseAssignment, CaseIndex, StaffRole, User

from .auth import Caller, StaffCaller, api_error

router = APIRouter(prefix="/v1/staff/admin", tags=["staff-admin"])
DUTY_ROLE = {"analyst": "analyst", "reviewer": "senior_reviewer"}


def _err(exc: handoffs.HandoffError):
    return api_error({"not_found": 404, "self_grant": 403, "last_admin": 409}.get(exc.code, 422), exc.code, exc.detail)


@router.get("/staff")
def list_staff(caller: Caller = StaffCaller):
    caller.require_staff("admin")
    with platform_session() as p:
        out = []
        for u in p.scalars(select(User).where(User.kind == "staff").order_by(User.username)):
            roles = p.scalars(select(StaffRole).where(StaffRole.user_id == u.id)).all()
            out.append({"user": u.username, "name": u.display_name, "active": u.active,
                        "roles": sorted(r.role for r in roles if r.active),
                        "history": [{"role": r.role, "active": r.active, "granted_by": r.granted_by, "granted_at": r.granted_at,
                                     "revoked_by": r.revoked_by, "revoked_at": r.revoked_at} for r in roles]})
        return {"staff": out, "assignable_roles": list(grants.STAFF_ROLES)}


def _change(username: str, role: str, active: bool, caller: Caller) -> dict:
    caller.require_staff("admin")
    with platform_session() as p:
        try:
            row = grants.set_staff_role(p, username=username.lower(), role=role, active=active, actor_id=caller.user_id, actor=caller.username)
        except handoffs.HandoffError as exc:
            raise _err(exc)
        ended = 0
        if not active:  # a duty without its role ends at once; the case manager reassigns it
            duty = next((d for d, r in DUTY_ROLE.items() if r == role), None)
            if duty:
                for a in p.scalars(select(CaseAssignment).where(CaseAssignment.staff_user_id == row.user_id, CaseAssignment.duty == duty,
                                                               CaseAssignment.active.is_(True))):
                    a.active, a.revoked_at = False, time.time()
                    ended += 1
        return {"user": username.lower(), "role": role, "active": row.active, "assignments_ended": ended}


@router.put("/staff/{username}/roles/{role}")
def grant_staff_role(username: str, role: str, caller: Caller = StaffCaller):
    return _change(username, role, True, caller)


@router.delete("/staff/{username}/roles/{role}")
def revoke_staff_role(username: str, role: str, caller: Caller = StaffCaller):
    return _change(username, role, False, caller)


@router.get("/workload")
def workload(caller: Caller = StaffCaller):
    """Active case load per staff member: counts, states and queue ages from the case index only."""
    caller.require_staff("admin", "case_manager")
    now = time.time()
    with platform_session() as p:
        index = {c.case_id: c for c in p.scalars(select(CaseIndex))}
        active = p.scalars(select(CaseAssignment).where(CaseAssignment.active.is_(True))).all()
        rows = []
        for u in p.scalars(select(User).where(User.kind == "staff").order_by(User.username)):
            mine = [a for a in active if a.staff_user_id == u.id and a.case_id in index]
            roles = sorted(r.role for r in p.scalars(select(StaffRole).where(StaffRole.user_id == u.id, StaffRole.active.is_(True))))
            ages = [now - index[a.case_id].updated_at for a in mine]
            rows.append({"user": u.username, "name": u.display_name, "roles": roles,
                         "analyst_cases": sum(a.duty == "analyst" for a in mine), "reviewer_cases": sum(a.duty == "reviewer" for a in mine),
                         "blocked_cases": sum(index[a.case_id].blockers > 0 for a in mine),
                         "oldest_case_hours": round(max(ages) / 3600, 1) if ages else 0})
        unassigned = [c.case_id for c in index.values() if c.state not in ("closed",) and not any(a.case_id == c.case_id and a.duty == "analyst" for a in active)]
        return {"staff": rows, "unassigned_cases": len(unassigned)}
