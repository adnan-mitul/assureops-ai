"""Backend handoffs: inquiry conversion, invitations, membership grants/revocation, notification outbox.

Notifications are written in the same transaction as the change that causes
them and delivered later by the dispatcher (SMTP when configured, otherwise a
local mail drop for development). Invitation tokens are shown once in the
notification and stored only as hashes.
"""

import hashlib
import os
import secrets
import smtplib
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import ROOT
from .models import Invitation, Membership, Notification, User, now

INVITATION_TTL = 7 * 86400
ROLES = ("owner", "developer", "reviewer", "viewer")


class HandoffError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def notify(session: Session, *, recipient: str, kind: str, subject: str, body: str, workspace_id: str | None = None) -> Notification:
    n = Notification(workspace_id=workspace_id, recipient=recipient, kind=kind, subject=subject, body=body)
    session.add(n)
    return n


def invite(session: Session, *, workspace_id: str, email: str, role: str, invited_by: str, portal_origin: str) -> tuple[Invitation, str]:
    if role not in ROLES:
        raise HandoffError("invalid_role", f"role must be one of {ROLES}")
    email = email.strip().lower()
    open_invite = session.scalars(select(Invitation).where(Invitation.workspace_id == workspace_id, Invitation.email == email,
                                                           Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
                                                           Invitation.expires_at > now())).first()
    if open_invite:
        raise HandoffError("already_invited", "an open invitation already exists for this address")
    token = "aoinv_" + secrets.token_urlsafe(24)
    inv = Invitation(workspace_id=workspace_id, email=email, role=role, token_hash=token_hash(token), invited_by=invited_by,
                     expires_at=now() + INVITATION_TTL)
    session.add(inv)
    notify(session, recipient=email, kind="invitation", workspace_id=workspace_id, subject="You are invited to an AssureOps workspace",
           body=(f"{invited_by} invited you to workspace {workspace_id} as {role}.\n"
                 f"Sign in and accept within 7 days: {portal_origin}/invitations/accept?token={token}\n"))
    return inv, token


def accept(session: Session, *, token: str, username: str, display_name: str) -> Membership:
    inv = session.scalars(select(Invitation).where(Invitation.token_hash == token_hash(token)).with_for_update()).first()
    if inv is None or inv.revoked_at or inv.accepted_at:
        raise HandoffError("invalid_invitation", "invitation is unknown, revoked or already used")
    if inv.expires_at < now():
        raise HandoffError("expired", "invitation expired; ask the owner for a new one")
    if inv.email != username.lower():
        raise HandoffError("wrong_account", "this invitation was sent to a different account")
    user = session.scalars(select(User).where(User.username == username)).first()
    if user is None:
        user = User(username=username, display_name=display_name or username, kind="customer")
        session.add(user)
        session.flush()
    if user.kind != "customer":
        raise HandoffError("wrong_account", "staff accounts cannot join customer workspaces")
    membership = session.scalars(select(Membership).where(Membership.workspace_id == inv.workspace_id, Membership.user_id == user.id)).first()
    if membership is None:
        membership = Membership(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role)
        session.add(membership)
    membership.role, membership.active = inv.role, True
    inv.accepted_at = now()
    return membership


def set_role(session: Session, *, workspace_id: str, username: str, role: str | None, actor: str) -> Membership:
    """Grant a new role or revoke membership (role=None). The last active owner cannot be removed or demoted."""
    user = session.scalars(select(User).where(User.username == username)).first()
    m = session.scalars(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)
                        .with_for_update()).first() if user else None
    if m is None:
        raise HandoffError("not_found", "member not found")
    if role is not None and role not in ROLES:
        raise HandoffError("invalid_role", f"role must be one of {ROLES}")
    if m.role == "owner" and role != "owner":
        owners = session.scalars(select(Membership).where(Membership.workspace_id == workspace_id, Membership.role == "owner",
                                                          Membership.active.is_(True))).all()
        if len(owners) <= 1:
            raise HandoffError("last_owner", "a workspace needs at least one active owner")
    if role is None:
        m.active = False
        notify(session, recipient=username, kind="membership_revoked", workspace_id=workspace_id,
               subject="Your AssureOps workspace access was removed", body=f"{actor} removed your access to workspace {workspace_id}.\n")
    else:
        m.role, m.active = role, True
        notify(session, recipient=username, kind="membership_changed", workspace_id=workspace_id,
               subject="Your AssureOps workspace role changed", body=f"{actor} set your role in workspace {workspace_id} to {role}.\n")
    return m


def deliver_pending(session: Session, limit: int = 20) -> int:
    rows = session.scalars(select(Notification).where(Notification.status == "pending").order_by(Notification.created_at)
                           .limit(limit).with_for_update(skip_locked=True)).all()
    for n in rows:
        n.attempts += 1
        try:
            _send(n)
            n.status, n.delivered_at, n.last_error = "delivered", now(), None
        except Exception as exc:  # bounded retries, then a visible failure
            n.last_error = f"{exc.__class__.__name__}: {exc}"[:500]
            if n.attempts >= 5:
                n.status = "failed"
    return len(rows)


def webhook_payload(n: Notification) -> dict:
    """Redacted: kind, subject and workspace only. Bodies (which may carry invitation links) and recipients never leave."""
    return {"id": n.id, "kind": n.kind, "subject": n.subject, "workspace_id": n.workspace_id, "created_at": round(n.created_at, 3)}


def _webhook(n: Notification):
    url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url:
        return
    import hmac
    import json

    import httpx

    body = json.dumps(webhook_payload(n), sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(os.environ.get("NOTIFY_WEBHOOK_SECRET", "").encode(), body, hashlib.sha256).hexdigest()
    res = httpx.post(url, content=body, timeout=10, follow_redirects=False,
                     headers={"Content-Type": "application/json", "X-AssureOps-Signature": f"sha256={signature}", "X-AssureOps-Delivery": n.id})
    if res.status_code >= 300:
        raise RuntimeError(f"webhook answered {res.status_code}")


def _send(n: Notification):
    _webhook(n)  # receivers dedupe on X-AssureOps-Delivery; a webhook grants no access to anything
    msg = EmailMessage()
    msg["From"] = os.environ.get("NOTIFY_FROM", "AssureOps <no-reply@assureops.test>")
    msg["To"] = n.recipient
    msg["Subject"] = n.subject
    msg.set_content(n.body)
    smtp_url = os.environ.get("NOTIFY_SMTP_HOST")
    if smtp_url:
        with smtplib.SMTP(smtp_url, int(os.environ.get("NOTIFY_SMTP_PORT", "587")), timeout=10) as smtp:
            smtp.starttls()
            if os.environ.get("NOTIFY_SMTP_USER"):
                smtp.login(os.environ["NOTIFY_SMTP_USER"], os.environ["NOTIFY_SMTP_PASSWORD"])
            smtp.send_message(msg)
        return
    drop = Path(os.environ.get("NOTIFY_MAIL_DROP", str(ROOT / "var" / "mail")))  # development mail drop
    drop.mkdir(parents=True, exist_ok=True)
    (drop / f"{n.id}.eml").write_bytes(bytes(msg))
