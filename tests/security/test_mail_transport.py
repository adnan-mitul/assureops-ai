"""Mail goes through Resend when a key is configured; refusals keep the mail locally with the reason, outages are retried."""

import types

import pytest

from assureops_domain import handoffs
from assureops_domain.models import Notification


def _notification():
    return Notification(id="ntf_test1", recipient="owner@example.test", kind="invitation", subject="You are invited", body="Open the link.\n")


class _Res:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def resend(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("RESEND_API_KEY", "re_test_only")
    monkeypatch.setenv("NOTIFY_MAIL_DROP", str(tmp_path))
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    fake = types.SimpleNamespace(answer=_Res(200, {"id": "email_1"}))

    def post(url, **kw):
        calls.append((url, kw))
        return fake.answer
    monkeypatch.setattr("httpx.post", post)
    return fake, calls, tmp_path


def test_sent_through_resend_with_idempotency_and_no_local_copy(resend):
    fake, calls, drop = resend
    assert handoffs._send(_notification()) is None
    url, kw = calls[0]
    assert url == "https://api.resend.com/emails" and kw["headers"]["Idempotency-Key"] == "ntf_test1"
    assert kw["json"]["to"] == ["owner@example.test"] and "onboarding@resend.dev" in kw["json"]["from"]
    assert not list(drop.iterdir())


def test_refused_recipient_is_kept_locally_with_the_reason(resend):
    fake, _, drop = resend
    fake.answer = _Res(403, {"message": "You can only send testing emails to your own email address"})
    note = handoffs._send(_notification())
    assert "resend refused (403)" in note and (drop / "ntf_test1.eml").exists()


def test_outage_raises_so_delivery_is_retried(resend):
    fake, _, _ = resend
    fake.answer = _Res(503)
    with pytest.raises(RuntimeError):
        handoffs._send(_notification())
