"""In-app inbox isolation and read state; webhook deliveries are signed and redacted."""

import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from assureops_api import routes_notifications as rn
from assureops_domain import handoffs
from assureops_domain.db import platform_session
from assureops_domain.models import Notification


def test_each_person_sees_only_their_own_notifications_for_the_active_workspace(workspace, people):
    dev, viewer = people["developer"], people["viewer"]
    with platform_session() as s:
        handoffs.notify(s, recipient=dev.username, kind="application_assigned", subject="mine", body="b", workspace_id=workspace)
        handoffs.notify(s, recipient=dev.username, kind="staff_role_changed", subject="account-level", body="b")
        handoffs.notify(s, recipient=dev.username, kind="application_assigned", subject="other workspace", body="b", workspace_id="acme")
        handoffs.notify(s, recipient=viewer.username, kind="invitation", subject="not yours", body="b", workspace_id=workspace)
    try:
        inbox = rn.customer_inbox(caller=dev)
        assert {n["subject"] for n in inbox["items"]} == {"mine", "account-level"} and inbox["unread"] == 2
        theirs = next(n for n in rn.customer_inbox(caller=viewer)["items"] if n["subject"] == "not yours")
        with pytest.raises(HTTPException) as exc:
            rn.customer_read(theirs["id"], caller=dev)  # cannot touch someone else's notification
        assert exc.value.status_code == 404
        mine = next(n for n in inbox["items"] if n["subject"] == "mine")
        assert rn.customer_read(mine["id"], caller=dev)["marked"] == 1
        assert rn.customer_inbox(caller=dev)["unread"] == 1
        assert rn.customer_read_all(caller=dev)["marked"] == 1 and rn.customer_inbox(caller=dev)["unread"] == 0
    finally:
        with platform_session() as s:
            s.execute(delete(Notification).where(Notification.recipient.in_([dev.username, viewer.username])))


def test_webhook_delivery_is_signed_and_never_carries_bodies_or_recipients(monkeypatch, tmp_path):
    sent = []

    def fake_post(url, content, timeout, follow_redirects, headers):
        sent.append((url, content, headers, follow_redirects))
        return httpx.Response(204)

    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/assureops")
    monkeypatch.setenv("NOTIFY_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("NOTIFY_MAIL_DROP", str(tmp_path))
    monkeypatch.setattr(httpx, "post", fake_post)
    with platform_session() as s:
        n = handoffs.notify(s, recipient="someone@acme.test", kind="invitation", subject="You are invited",
                            body="Accept: http://x/invitations/accept?token=aoinv_secret_link", workspace_id="acme")
        s.flush()
        nid = n.id
    try:
        with platform_session() as s:
            handoffs._send(s.get(Notification, nid))
        url, content, headers, follow = sent[0]
        payload = json.loads(content)
        assert set(payload) == {"id", "kind", "subject", "workspace_id", "created_at"}
        assert b"aoinv_secret_link" not in content and b"someone@acme.test" not in content
        assert headers["X-AssureOps-Signature"] == "sha256=" + hmac.new(b"test-webhook-secret", content, hashlib.sha256).hexdigest()
        assert headers["X-AssureOps-Delivery"] == nid and follow is False
    finally:
        with platform_session() as s:
            s.execute(delete(Notification).where(Notification.id == nid))
