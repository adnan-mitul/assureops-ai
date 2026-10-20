"""Durable AI phase jobs: proposal, separation of duties, stale owners, bounded retries, policy denial without dispatch."""

import json

import pytest
from sqlalchemy import select, text

from assureops_ai import router, service
from assureops_ai.providers.base import ProviderResult
from assureops_domain.db import tenant_session
from assureops_domain.models import AiResult, Application, ApplicationProfile, ModelCall, Outbox


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def json_mode(self, model):
        return "json_schema"

    def generate(self, **kwargs):
        self.calls += 1
        return self.results.pop(0) if self.results else self.results_last

    @property
    def results_last(self):
        return ProviderResult("unavailable", "private", "fake", error="exhausted")


C_OUTPUT = {"tests": [{"template": "auth_required", "control": "C01", "name": "Chat rejects missing identity",
                       "args": {"request": {"method": "POST", "path": "/chat", "body": {"message": "hi"}}}}], "unknowns": []}


@pytest.fixture
def private_route(monkeypatch):
    route = router.Route("C", "private", "fake-model", True, "test route")
    monkeypatch.setattr(router, "resolve", lambda phase, allowed: route)
    return route


def _request(ws, phase="C", actor="dev@acme.test"):
    with tenant_session(ws) as s:
        app = s.get(Application, f"{ws}-app")
        return service.request(s, app, phase, {}, actor).id


def test_valid_output_becomes_a_proposal_and_review_creates_only_another_proposal(workspace, private_route, monkeypatch):
    fake = FakeClient([ProviderResult("succeeded", "private", "fake-model", content=json.dumps(C_OUTPUT), parsed=C_OUTPUT,
                                      usage={"total_tokens": 42}, request_id="r1", latency_ms=5)])
    monkeypatch.setattr(router, "generation_client", lambda route: fake)
    rid = _request(workspace)
    assert service.execute(workspace, rid) == "proposed"
    with tenant_session(workspace) as s:
        row = s.get(AiResult, rid)
        call = s.get(ModelCall, row.model_call_id)
        assert call.usage["total_tokens"] == 42 and call.status == "succeeded" and call.input_sha256
        with pytest.raises(service.AiError) as exc:
            service.review(s, row, decision="accept", reviewer="dev@acme.test", note="mine")
        assert exc.value.code == "separation_of_duties"
        effects = service.review(s, row, decision="accept", reviewer="reviewer@acme.test", note="ok")
        assert row.status == "accepted" and "profile_revision_proposed" in effects
        proposed = s.scalars(select(ApplicationProfile).where(ApplicationProfile.status == "proposed")).one()
        assert proposed.proposed_by.startswith("ai:")  # still needs a human activation


def test_retryable_failures_are_bounded_then_unavailable(workspace, private_route, monkeypatch):
    fake = FakeClient([ProviderResult("timeout", "private", "fake-model", error="slow")] * 5)
    monkeypatch.setattr(router, "generation_client", lambda route: fake)
    rid = _request(workspace)
    outcomes = [service.execute(workspace, rid) for _ in range(service.MAX_ATTEMPTS + 1)]
    assert outcomes[:2] == ["pending", "pending"] and outcomes[2] == "unavailable" and outcomes[3] == "not_claimable"
    with tenant_session(workspace) as s:
        assert s.get(AiResult, rid).status == "unavailable"


def test_invalid_output_never_becomes_a_proposal(workspace, private_route, monkeypatch):
    bad = {"tests": [{"template": "run_shell", "control": "C01", "name": "x", "args": {}}], "unknowns": []}
    fake = FakeClient([ProviderResult("succeeded", "private", "fake-model", content=json.dumps(bad), parsed=bad)])
    monkeypatch.setattr(router, "generation_client", lambda route: fake)
    rid = _request(workspace)
    assert service.execute(workspace, rid) == "review_required"
    with tenant_session(workspace) as s:
        row = s.get(AiResult, rid)
        with pytest.raises(service.AiError):
            service.review(s, row, decision="accept", reviewer="reviewer@acme.test", note="no")


def test_stale_owner_cannot_commit(workspace, private_route, monkeypatch):
    rid = _request(workspace)
    token = service.claim(workspace, rid)
    with tenant_session(workspace) as s:  # another worker took the job over
        s.execute(text("UPDATE ai_results SET fencing_token = fencing_token + 1 WHERE id = :id"), {"id": rid})
    assert service._finish(workspace, rid, token, "proposed", output=C_OUTPUT) == "stale_owner"
    with tenant_session(workspace) as s:
        assert s.get(AiResult, rid).status == "running"


def test_private_only_workspace_sends_nothing_to_an_external_route(workspace, monkeypatch):
    calls = []
    monkeypatch.setattr(router, "generation_client", lambda route: calls.append(route) or FakeClient([]))
    monkeypatch.setattr(router, "resolve", lambda phase, allowed: router.Route(phase, "groq", "m", False,
                        "external_processing_not_allowed: workspace is private-only", external=True))
    rid = _request(workspace)
    assert service.execute(workspace, rid) == "unavailable"
    assert calls == []
    with tenant_session(workspace) as s:
        assert "external_processing_not_allowed" in s.get(AiResult, rid).error
        assert s.scalars(select(Outbox).where(Outbox.ref_id == rid)).first() is not None  # the original dispatch intent only


def test_a_late_external_reply_after_cancellation_is_never_stored(workspace, monkeypatch):
    """Groq answers after the job was cancelled: the call is kept for cost accounting, the output is discarded."""
    route = router.Route("C", "groq", "openai/gpt-oss-20b", True, "test external route", external=True)
    monkeypatch.setattr(router, "resolve", lambda phase, allowed: route)
    monkeypatch.setattr(service, "external_allowed", lambda ws: True)
    rid = _request(workspace)

    class LateClient(FakeClient):
        def generate(self, **kwargs):
            with tenant_session(workspace) as s:  # the user cancels while the provider is still working
                assert service.cancel(s, s.get(AiResult, rid), actor="dev@acme.test")
            return ProviderResult("succeeded", "groq", route.model, content=json.dumps(C_OUTPUT), parsed=C_OUTPUT,
                                  usage={"total_tokens": 99}, request_id="late-1", latency_ms=900)

    monkeypatch.setattr(router, "generation_client", lambda r: LateClient([]))
    assert service.execute(workspace, rid) == "stale_owner"
    with tenant_session(workspace) as s:
        row = s.get(AiResult, rid)
        assert row.status == "cancelled" and row.output in (None, {}) and row.model_call_id is None
        late = s.scalars(select(ModelCall).where(ModelCall.job_ref == rid)).one()
        assert late.status == "stale_owner" and late.provider == "groq" and late.usage["total_tokens"] == 99
    assert service.claim(workspace, rid) is None  # a cancelled job is never picked up again
