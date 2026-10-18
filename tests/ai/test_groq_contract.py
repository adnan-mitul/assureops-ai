"""Groq provider contract, phase routing policy and output validation (no network, no key)."""

import json

import httpx
import pytest
from sqlalchemy import delete

from assureops_ai import router, validation
from assureops_ai.providers.groq import GroqProvider, fits_constraint, parameters_billion
from assureops_domain.config import settings
from assureops_domain.db import platform_session
from assureops_domain.models import ModelQualification


def provider(handler, calls=None):
    def wrapped(request: httpx.Request):
        if calls is not None:
            calls.append(request)
        return handler(request)
    return GroqProvider("https://api.groq.test/openai/v1", "test-key-not-real", timeout=2, max_retries=2, transport=httpx.MockTransport(wrapped))


def ok_body(content: str, finish="stop"):
    return {"id": "req-1", "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def gen(p):
    return p.generate(model="m", system="s", user="u", max_tokens=50)


@pytest.mark.parametrize("status,expected", [(401, "auth_failed"), (404, "model_unavailable"), (400, "invalid_request")])
def test_http_errors_map_to_typed_states(status, expected):
    r = gen(provider(lambda req: httpx.Response(status, json={"error": {"message": "x"}})))
    assert r.status == expected and not r.ok


def test_rate_limit_is_retried_with_a_bound(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = []
    r = gen(provider(lambda req: httpx.Response(429, json={}), calls))
    assert r.status == "rate_limited" and len(calls) == 3 and r.attempts == 3


def test_retry_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    seq = iter([httpx.Response(503), httpx.Response(200, json=ok_body('{"sections": [], "unknowns": []}'))])
    r = gen(provider(lambda req: next(seq)))
    assert r.ok and r.usage["total_tokens"] == 15 and r.request_id == "req-1" and r.attempts == 2


def test_malformed_refused_and_truncated_outputs():
    assert gen(provider(lambda req: httpx.Response(200, json=ok_body("not json")))).status == "invalid_output"
    assert gen(provider(lambda req: httpx.Response(200, json=ok_body("{}", finish="content_filter")))).status == "refused"
    assert gen(provider(lambda req: httpx.Response(200, json=ok_body('{"a"', finish="length")))).status == "invalid_output"
    assert gen(provider(lambda req: httpx.Response(200, json={"weird": True}))).status == "invalid_output"


def test_key_only_in_authorization_header():
    calls = []
    gen(provider(lambda req: httpx.Response(200, json=ok_body("{}")), calls))
    req = calls[0]
    assert req.headers["authorization"] == "Bearer test-key-not-real"
    assert "test-key-not-real" not in req.content.decode() and "test-key-not-real" not in str(req.url)
    assert json.loads(req.content)["temperature"] == 0


def test_model_size_constraint():
    assert parameters_billion("llama-3.1-8b-instant") == 8
    assert not fits_constraint("llama-3.3-70b-versatile", 3.8)
    assert fits_constraint("some-3b-model", 3.8)
    assert not fits_constraint("unknown-size-model", 3.8)


@pytest.fixture
def groq_cfg(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "groq_enabled", True)
    monkeypatch.setattr(cfg, "groq_api_key", "test-key-not-real")
    monkeypatch.setattr(cfg, "groq_model_f", "tiny-3b-test")
    monkeypatch.delenv("PRIVATE_INFERENCE_URL", raising=False)
    yield cfg
    with platform_session() as s:
        s.execute(delete(ModelQualification).where(ModelQualification.model == "tiny-3b-test"))


def test_routing_requires_policy_and_qualification(groq_cfg, monkeypatch):
    assert router.resolve("F", external_allowed=False).reason.startswith("external_processing_not_allowed")
    assert router.resolve("F", external_allowed=True).reason.startswith("not_qualified")
    with platform_session() as s:
        s.add(ModelQualification(phase="F", provider="groq", model="tiny-3b-test", artifact_digest="x", prompt_version="F-2", schema_version="F-2",
                                 dataset="holdout", metrics={}, status="qualified", recorded_by="test"))
    route = router.resolve("F", external_allowed=True)
    assert route.available and route.provider == "groq" and route.external
    assert not router.resolve("A", external_allowed=True).available  # phase A is not approved for external processing
    monkeypatch.setattr(groq_cfg, "groq_api_key", "")
    assert router.resolve("F", external_allowed=True).reason.startswith("key_missing")
    monkeypatch.setattr(groq_cfg, "groq_enabled", False)
    assert router.resolve("F", external_allowed=True).reason.startswith("provider_disabled")


def test_oversized_model_stays_disabled_without_explicit_exception(groq_cfg, monkeypatch):
    monkeypatch.setattr(groq_cfg, "groq_model_f", "llama-3.3-70b-versatile")
    assert router.resolve("F", external_allowed=True).reason.startswith("constraint_exceeded")


def test_explanation_validation_rejects_new_numbers_and_verdicts():
    facts = {"F-gate": "Release gate status for R3 is ready", "F-scores": "Evidence support 50% and coverage 50% across 10 controls"}
    good = {"sections": [{"heading": "Status", "text": "Coverage is 50% across 10 controls.", "fact_ids": ["F-scores"]}], "unknowns": []}
    assert validation.validate("F", good, {"facts": facts})["status"] == "valid"
    stray = {"sections": [{"heading": "Status", "text": "Coverage is 95%.", "fact_ids": ["F-scores"]}], "unknowns": []}
    assert validation.validate("F", stray, {"facts": facts})["status"] == "unsupported_claims"
    verdict = {"sections": [{"heading": "Status", "text": "The application is certified.", "fact_ids": ["F-gate"]}], "unknowns": []}
    assert validation.validate("F", verdict, {"facts": facts})["status"] == "unsupported_claims"
    assert validation.validate("F", {"sections": "x"}, {"facts": facts})["status"] == "invalid_output"
    negated = {"sections": [{"heading": "Scope", "text": "This is not a certification.", "fact_ids": ["F-gate"]}], "unknowns": []}
    assert validation.validate("F", negated, {"facts": facts})["status"] == "valid"


def test_requirement_quotes_must_exist_in_authorized_sources():
    out = {"requirements": [{"statement": "Refunds need approval", "control": "C03", "spans": [{"source_id": "s1", "quote": "need manager approval"}]}],
           "unknowns": []}
    assert validation.validate("A", out, {"sources": {"s1": "Refunds above 1000 need manager approval."}})["status"] == "valid"
    assert validation.validate("A", out, {"sources": {"s1": "Something else entirely."}})["status"] == "unsupported_claims"
    assert validation.validate("A", out, {"sources": {"s2": "need manager approval"}})["status"] == "unsupported_claims"


def test_redaction_before_external_dispatch():
    text = "contact ops@acme.test with key sk-live-ABCDEFGH1234 and gsk_abcdefgh12345"
    red = validation.minimize(text)
    assert "ops@acme.test" not in red and "sk-live" not in red and "gsk_" not in red
