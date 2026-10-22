"""In-app inbox for customers and staff. Each person sees only notifications addressed to them."""

from fastapi import APIRouter
from sqlalchemy import or_, select

from assureops_domain.db import platform_session
from assureops_domain.models import Notification, now

from .auth import Caller, CustomerCaller, StaffCaller, api_error

router = APIRouter(prefix="/v1", tags=["notifications"])
INBOX_LIMIT = 50


def _query(caller: Caller):
    q = select(Notification).where(Notification.recipient == caller.username)
    if caller.kind == "customer":  # only the workspace the request is acting in, plus account-level notices
        q = q.where(or_(Notification.workspace_id == caller.workspace_id, Notification.workspace_id.is_(None)))
    return q


def _inbox(caller: Caller) -> dict:
    with platform_session() as s:
        rows = s.scalars(_query(caller).order_by(Notification.created_at.desc()).limit(INBOX_LIMIT)).all()
        unread = sum(1 for n in s.scalars(_query(caller).where(Notification.read_at.is_(None))))
        return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "subject": n.subject, "body": n.body, "workspace_id": n.workspace_id,
                                            "created_at": n.created_at, "read_at": n.read_at, "delivery": n.status} for n in rows]}


def _mark(caller: Caller, notification_id: str | None) -> dict:
    with platform_session() as s:
        q = _query(caller).where(Notification.read_at.is_(None))
        if notification_id:
            q = q.where(Notification.id == notification_id)
        rows = s.scalars(q).all()
        if notification_id and not rows:
            exists = s.scalars(_query(caller).where(Notification.id == notification_id)).first()
            if exists is None:
                raise api_error(404, "not_found", "notification not found")
        for n in rows:
            n.read_at = now()
        return {"marked": len(rows)}


@router.get("/notifications")
def customer_inbox(caller: Caller = CustomerCaller):
    return _inbox(caller)


@router.post("/notifications/{notification_id}/read")
def customer_read(notification_id: str, caller: Caller = CustomerCaller):
    return _mark(caller, notification_id)


@router.post("/notifications/read-all")
def customer_read_all(caller: Caller = CustomerCaller):
    return _mark(caller, None)


@router.get("/staff/notifications")
def staff_inbox(caller: Caller = StaffCaller):
    return _inbox(caller)


@router.post("/staff/notifications/{notification_id}/read")
def staff_read(notification_id: str, caller: Caller = StaffCaller):
    return _mark(caller, notification_id)


@router.post("/staff/notifications/read-all")
def staff_read_all(caller: Caller = StaffCaller):
    return _mark(caller, None)
