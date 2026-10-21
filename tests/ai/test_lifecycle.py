"""Model route lifecycle: qualification gates, shadow evidence, canary split, separation of duties, rollback, fair admission."""

import json
import uuid

import pytest
from sqlalchemy import delete, select

from assureops_ai import lifecycle, router, service
from assureops_ai.providers.base import ProviderResult
from assureops_ai.registry import PHASES
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import AiResult, Application, ModelQualification, ModelRouteEvent, ModelRouteStage, Outbox
from tests.ai.test_ai_pipeline import C_OUTPUT, FakeClient

PHASE = "C"


@pytest.fixture
def candidates():
    """Two fake private candidates for phase C; everything they create is removed so real routing is untouched."""
    tag = uuid.uuid4().hex[:6]
    names = [f"test-cand-a-{tag}", f"test-cand-b-{tag}"]
    yield names
    with platform_session() as p:
        ids = [r.id for r in p.scalars(select(ModelRouteStage).where(ModelRouteStage.model.in_(names)))]
        p.execute(delete(ModelRouteEvent).where(ModelRouteEvent.route_id.in_(ids)))
        p.execute(delete(ModelRouteStage).where(ModelRouteStage.id.in_(ids)))
        p.execute(delete(ModelQualification).where(ModelQualification.model.in_(names)))


def _qualify(model: str):
    phase = PHASES[PHASE]
    with platform_session() as p:
        p.add(ModelQualification(phase=PHASE, provider="private", model=model, artifact_digest="test", prompt_version=phase.prompt_version,
                                 schema_version=phase.schema_version, dataset="test", metrics={}, status="qualified", recorded_by="test"))


def _code(fn) -> str:
    with pytest.raises(lifecycle.LifecycleError) as exc:
        fn()
    return exc.value.code


def _to(route_id: str, to: str, actor: str, **counters):
    with platform_session() as p:
        row = p.get(ModelRouteStage, route_id)
        for k, v in counters.items():
            setattr(row, k, v)
        lifecycle.transition(p, row, to=to, actor=actor, note="test")


def test_promotion_needs_qualification_evidence_and_a_second_person_and_rollback_restores(candidates, monkeypatch):
    monkeypatch.setenv("PRIVATE_INFERENCE_URL", "http://127.0.0.1:9/v1")
    a, b = candidates
    with platform_session() as p:
        ra = lifecycle.register(p, phase=PHASE, provider="private", model=a, actor="op1").id
        assert _code(lambda: lifecycle.register(p, phase=PHASE, provider="groq", model="x", actor="op1")) == "invalid_route"  # C is not approved for Groq
    _to(ra, "holdout", "op1")
    with platform_session() as p:
        assert _code(lambda: lifecycle.transition(p, p.get(ModelRouteStage, ra), to="shadow", actor="op1", note="x")) == "not_qualified"
    _qualify(a)
    _to(ra, "shadow", "op1")
    with platform_session() as p:
        assert _code(lambda: lifecycle.transition(p, p.get(ModelRouteStage, ra), to="canary", actor="op1", note="x")) == "insufficient_evidence"
    _to(ra, "canary", "op1", shadow_runs=5, shadow_valid=4)
    with platform_session() as p:
        row = p.get(ModelRouteStage, ra)
        row.canary_runs, row.canary_valid = 6, 6
        assert _code(lambda: lifecycle.transition(p, row, to="active", actor="op1", note="x")) == "separation_of_duties"
        row.canary_invalid = 1
        assert _code(lambda: lifecycle.transition(p, row, to="active", actor="op2", note="x")) == "insufficient_evidence"
    _to(ra, "active", "op2", canary_invalid=0)
    route = router.resolve(PHASE, False, key="any")
    assert (route.model, route.stage, route.available) == (a, "active", True)

    with platform_session() as p:  # a second candidate replaces it, then is rolled back
        rb = lifecycle.register(p, phase=PHASE, provider="private", model=b, actor="op1").id
    _qualify(b)
    _to(rb, "holdout", "op1")
    _to(rb, "shadow", "op1")
    _to(rb, "canary", "op1", shadow_runs=5, shadow_valid=5)
    _to(rb, "active", "op2", canary_runs=5, canary_valid=5)
    with platform_session() as p:
        assert p.get(ModelRouteStage, ra).stage == "retired" and p.get(ModelRouteStage, rb).replaces_id == ra
    assert router.resolve(PHASE, False).model == b
    with platform_session() as p:
        assert lifecycle.rollback(p, PHASE, actor="op2", note="regression") == {"rolled_back": rb, "restored": ra}
    assert router.resolve(PHASE, False).model == a


def test_a_canary_serves_only_its_share_of_requests(candidates, monkeypatch):
    monkeypatch.setenv("PRIVATE_INFERENCE_URL", "http://127.0.0.1:9/v1")
    a, _ = candidates
    _qualify(a)
    with platform_session() as p:
        row = lifecycle.register(p, phase=PHASE, provider="private", model=a, actor="op1")
        row.canary_percent = 30
        rid = row.id
    _to(rid, "holdout", "op1")
    _to(rid, "canary", "op1")  # private routes may skip shadow; evidence then comes from the canary alone
    keys = [f"air_{i}" for i in range(400)]
    share = sum(router.resolve(PHASE, False, key=k).stage == "canary" for k in keys) / len(keys)
    assert 0.2 < share < 0.4
    assert router.resolve(PHASE, False, key=keys[0]).stage == router.resolve(PHASE, False, key=keys[0]).stage  # stable per request


def test_shadow_runs_are_counted_never_reviewed_and_never_listed(workspace, candidates, monkeypatch):
    monkeypatch.setenv("PRIVATE_INFERENCE_URL", "http://127.0.0.1:9/v1")
    a, _ = candidates
    _qualify(a)
    with platform_session() as p:
        rid = lifecycle.register(p, phase=PHASE, provider="private", model=a, actor="op1").id
    _to(rid, "holdout", "op1")
    _to(rid, "shadow", "op1")
    primary = router.Route(PHASE, "private", "serving-model", True, "test", stage="unmanaged")
    real_resolve = router.resolve
    monkeypatch.setattr(router, "resolve", lambda phase, allowed, key=None: primary if phase == PHASE else real_resolve(phase, allowed, key))
    ok = ProviderResult("succeeded", "private", "m", content=json.dumps(C_OUTPUT), parsed=C_OUTPUT, usage={"total_tokens": 3})
    monkeypatch.setattr(router, "generation_client", lambda route: FakeClient([ok, ok]))
    with tenant_session(workspace) as s:
        first = service.request(s, s.get(Application, f"{workspace}-app"), PHASE, {}, "dev@acme.test").id
    assert service.execute(workspace, first) == "proposed"
    with tenant_session(workspace) as s:
        shadow = s.scalars(select(AiResult).where(AiResult.shadow_of == first)).one()
        shadow_id = shadow.id
    assert service.execute(workspace, shadow_id) == "shadow"
    with tenant_session(workspace) as s:
        row = s.get(AiResult, shadow_id)
        assert row.versions["shadow_outcome"] == "proposed" and row.versions["model"] == a
        with pytest.raises(service.AiError) as exc:
            service.review(s, row, decision="accept", reviewer="reviewer@acme.test", note="no")
        assert exc.value.code == "shadow"
        assert not s.scalars(select(AiResult).where(AiResult.shadow_of == shadow_id)).all()  # shadows never spawn shadows
    with platform_session() as p:
        assert (p.get(ModelRouteStage, rid).shadow_runs, p.get(ModelRouteStage, rid).shadow_valid) == (1, 1)
    from assureops_api import ai_routes
    from assureops_api.auth import Caller

    listed = ai_routes.list_results(f"{workspace}-app", caller=Caller("u", "viewer@x", "v", "customer", workspace_id=workspace, role="viewer",
                                                                     memberships={workspace: "viewer"}))
    assert shadow_id not in {r["id"] for r in listed} and first in {r["id"] for r in listed}


def test_one_workspace_cannot_fill_the_shared_queue(workspace, monkeypatch):
    monkeypatch.setattr(service, "MAX_QUEUED_PER_WORKSPACE", 3)
    with tenant_session(workspace) as s:
        app = s.get(Application, f"{workspace}-app")
        for _ in range(3):
            service.request(s, app, PHASE, {}, "dev@acme.test")
        with pytest.raises(service.AiError) as exc:
            service.request(s, app, PHASE, {}, "dev@acme.test")
        assert exc.value.code == "queue_full"
        s.execute(delete(Outbox).where(Outbox.workspace_id == workspace, Outbox.kind == "ai_phase"))
