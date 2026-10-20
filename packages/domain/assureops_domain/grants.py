"""Application-scoped developer grants and staff role administration.

A customer developer changes only the applications an owner assigned to them;
an expired or revoked grant stops access on the next request. Staff roles are
granted and revoked by an AssureOps admin, never by the person receiving them,
and the last active admin cannot be removed.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .handoffs import HandoffError, notify
from .models import Application, ApplicationGrant, Membership, StaffRole, User, now

STAFF_ROLES = ("admin", "analyst", "senior_reviewer", "case_manager", "operator")


def active_grant(session: Session, application_id: str, user_id: str) -> ApplicationGrant | None:
    return session.scalars(select(ApplicationGrant).where(
        ApplicationGrant.application_id == application_id, ApplicationGrant.user_id == user_id, ApplicationGrant.revoked_at.is_(None),
        or_(ApplicationGrant.expires_at.is_(None), ApplicationGrant.expires_at > now()))).first()


def assign_developer(tenant: Session, platform: Session, *, workspace_id: str, application_id: str, username: str, actor: str,
                     expires_at: float | None = None) -> ApplicationGrant:
    """Owner assigns an active developer of the same workspace to one application (idempotent)."""
    if tenant.get(Application, application_id) is None:
        raise HandoffError("not_found", "application not found")
    user = platform.scalars(select(User).where(User.username == username, User.active.is_(True))).first()
    member = platform.scalars(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id,
                                                       Membership.active.is_(True))).first() if user else None
    if member is None:
        raise HandoffError("not_found", "no active member with that username in this workspace")
    if member.role != "developer":
        raise HandoffError("invalid_role", f"only developers are assigned to applications ({username} is {member.role})")
    if expires_at is not None and expires_at <= now():
        raise HandoffError("invalid_expiry", "expiry must be in the future")
    grant = active_grant(tenant, application_id, user.id)
    if grant is None:
        grant = ApplicationGrant(workspace_id=workspace_id, application_id=application_id, user_id=user.id, granted_by=actor, expires_at=expires_at)
        tenant.add(grant)
        notify(platform, recipient=username, kind="application_assigned", workspace_id=workspace_id,
               subject=f"You were assigned to {application_id}", body=f"{actor} assigned you to application {application_id} in workspace {workspace_id}.\n")
    else:
        grant.expires_at = expires_at
    return grant


def unassign_developer(tenant: Session, platform: Session, *, workspace_id: str, application_id: str, username: str, actor: str) -> bool:
    user = platform.scalars(select(User).where(User.username == username)).first()
    grant = active_grant(tenant, application_id, user.id) if user else None
    if grant is None:
        return False
    grant.revoked_at, grant.revoked_by = now(), actor
    notify(platform, recipient=username, kind="application_unassigned", workspace_id=workspace_id,
           subject=f"Your assignment to {application_id} ended", body=f"{actor} removed your assignment to application {application_id}.\n")
    return True


def application_developers(tenant: Session, platform: Session, application_id: str) -> list[dict]:
    rows = tenant.scalars(select(ApplicationGrant).where(ApplicationGrant.application_id == application_id)
                          .order_by(ApplicationGrant.granted_at.desc())).all()
    names = {u.id: u for u in platform.scalars(select(User).where(User.id.in_([g.user_id for g in rows])))} if rows else {}
    t = now()
    return [{"user": names[g.user_id].username if g.user_id in names else g.user_id,
             "display_name": names[g.user_id].display_name if g.user_id in names else "",
             "granted_by": g.granted_by, "granted_at": g.granted_at, "expires_at": g.expires_at,
             "revoked_at": g.revoked_at, "revoked_by": g.revoked_by,
             "active": g.revoked_at is None and (g.expires_at is None or g.expires_at > t)} for g in rows]


def assigned_application_ids(tenant: Session, user_id: str) -> set[str]:
    return {g.application_id for g in tenant.scalars(select(ApplicationGrant).where(
        ApplicationGrant.user_id == user_id, ApplicationGrant.revoked_at.is_(None),
        or_(ApplicationGrant.expires_at.is_(None), ApplicationGrant.expires_at > now())))}


# ---------------- Staff role administration ----------------

def set_staff_role(platform: Session, *, username: str, role: str, active: bool, actor_id: str, actor: str) -> StaffRole:
    if role not in STAFF_ROLES:
        raise HandoffError("invalid_role", f"role must be one of {STAFF_ROLES}")
    user = platform.scalars(select(User).where(User.username == username, User.kind == "staff")).first()
    if user is None:
        raise HandoffError("not_found", "no staff account with that username")
    if user.id == actor_id:
        raise HandoffError("self_grant", "staff roles are changed by another admin, never by the person receiving them")
    row = platform.scalars(select(StaffRole).where(StaffRole.user_id == user.id, StaffRole.role == role).with_for_update()).first()
    if not active and role == "admin" and row is not None and row.active:
        admins = platform.scalars(select(StaffRole).where(StaffRole.role == "admin", StaffRole.active.is_(True))).all()
        if len(admins) <= 1:
            raise HandoffError("last_admin", "AssureOps needs at least one active admin")
    if row is None:
        if not active:
            raise HandoffError("not_found", f"{username} does not hold {role}")
        row = StaffRole(user_id=user.id, role=role)
        platform.add(row)
    if active:
        row.active, row.granted_by, row.granted_at, row.revoked_by, row.revoked_at = True, actor, now(), None, None
    elif row.active:
        row.active, row.revoked_by, row.revoked_at = False, actor, now()
    notify(platform, recipient=username, kind="staff_role_changed", subject="Your AssureOps staff role changed",
           body=f"{actor} {'granted' if active else 'revoked'} the {role} role.\n")
    return row
