"""Invitations, membership grants/revocation and notification outbox delivery."""

import uuid

import pytest
from sqlalchemy import delete, select

from assureops_domain import handoffs
from assureops_domain.db import platform_session
from assureops_domain.models import Invitation, Membership, Notification, User, now


@pytest.fixture
def mail_drop(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_MAIL_DROP", str(tmp_path))
    monkeypatch.delenv("NOTIFY_SMTP_HOST", raising=False)
    return tmp_path


def test_invitation_is_single_use_and_bound_to_the_invited_account(workspace, mail_drop):
    email = f"new-{uuid.uuid4().hex[:6]}@acme.test"
    try:
        with platform_session() as s:
            inv, token = handoffs.invite(s, workspace_id=workspace, email=email, role="developer", invited_by="owner@acme.test", portal_origin="http://x")
            assert token not in inv.token_hash
        with platform_session() as s:
            with pytest.raises(handoffs.HandoffError) as exc:
                handoffs.accept(s, token=token, username="someone-else@acme.test", display_name="x")
            assert exc.value.code == "wrong_account"
        with platform_session() as s:
            m = handoffs.accept(s, token=token, username=email, display_name="New Dev")
            assert m.role == "developer" and m.workspace_id == workspace
        with platform_session() as s:
            with pytest.raises(handoffs.HandoffError):
                handoffs.accept(s, token=token, username=email, display_name="New Dev")  # single use
            assert handoffs.deliver_pending(s) >= 1
        assert any(email in p.read_text(encoding="utf-8") for p in mail_drop.glob("*.eml"))
    finally:
        with platform_session() as s:
            user = s.scalars(select(User).where(User.username == email)).first()
            if user:
                s.execute(delete(Membership).where(Membership.user_id == user.id))
                s.delete(user)
            s.execute(delete(Invitation).where(Invitation.workspace_id == workspace))
            s.execute(delete(Notification).where(Notification.workspace_id == workspace))


def test_expired_invitation_is_refused(workspace, mail_drop):
    with platform_session() as s:
        inv, token = handoffs.invite(s, workspace_id=workspace, email="late@acme.test", role="viewer", invited_by="o", portal_origin="http://x")
        inv.expires_at = now() - 1
    try:
        with platform_session() as s:
            with pytest.raises(handoffs.HandoffError) as exc:
                handoffs.accept(s, token=token, username="late@acme.test", display_name="Late")
            assert exc.value.code == "expired"
    finally:
        with platform_session() as s:
            s.execute(delete(Invitation).where(Invitation.workspace_id == workspace))
            s.execute(delete(Notification).where(Notification.workspace_id == workspace))


def test_last_owner_cannot_be_removed_and_revocation_notifies(workspace, mail_drop):
    owner = f"own-{uuid.uuid4().hex[:6]}@acme.test"
    with platform_session() as s:
        u = User(username=owner, display_name="Owner", kind="customer")
        s.add(u)
        s.flush()
        s.add(Membership(workspace_id=workspace, user_id=u.id, role="owner"))
    try:
        with platform_session() as s:
            with pytest.raises(handoffs.HandoffError) as exc:
                handoffs.set_role(s, workspace_id=workspace, username=owner, role=None, actor="x")
            assert exc.value.code == "last_owner"
        with platform_session() as s:
            u2 = User(username=f"dev-{uuid.uuid4().hex[:6]}@acme.test", display_name="Dev", kind="customer")
            s.add(u2)
            s.flush()
            s.add(Membership(workspace_id=workspace, user_id=u2.id, role="developer"))
            dev = u2.username
        with platform_session() as s:
            m = handoffs.set_role(s, workspace_id=workspace, username=dev, role=None, actor=owner)
            assert m.active is False
            assert s.scalars(select(Notification).where(Notification.recipient == dev, Notification.kind == "membership_revoked")).first()
    finally:
        with platform_session() as s:
            for user in s.scalars(select(User).where(User.username.in_([owner, locals().get("dev", "")]))).all():
                s.execute(delete(Membership).where(Membership.user_id == user.id))
                s.delete(user)
            s.execute(delete(Notification).where(Notification.workspace_id == workspace))
