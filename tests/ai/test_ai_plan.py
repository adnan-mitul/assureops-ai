"""AI-built test plan: any connected application gets a proposed profile from its accepted phase A and C proposals."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from assureops_ai import service
from assureops_api import ai_routes, routes_handoffs, routes_onboarding
from assureops_domain.db import tenant_session
from assureops_domain.models import AiResult, Application, ApplicationProfile, Connection, Release

CHAT = {"method": "POST", "path": "/chat", "body": {"message": "hello"}}


def _denied(fn) -> str:
    with pytest.raises(HTTPException) as exc:
        fn()
    return exc.value.detail["code"]


@pytest.fixture
def generic_app(workspace):
    """A newly connected HTTP/JSON application with no profile file and no reference documents."""
    app_id = f"{workspace}-gen"
    with tenant_session(workspace) as s:
        s.add(Application(id=app_id, workspace_id=workspace, name="Support bot", purpose="Answers billing questions for signed-in customers.",
                          environment="staging", mode="enforce_supported_actions", target_url="http://127.0.0.1:9", tools_url=""))
        s.flush()
        s.add(Connection(workspace_id=workspace, application_id=app_id, revision=1, adapter_id="assureops-http-json-v1", adapter_version="1",
                         config={"base_url": "http://127.0.0.1:9", "actors": {"customer": {}, "other_tenant": {}},
                                 "scope": {"allowed_paths": ["/chat"]}}, status="verified", created_by="dev"))
        m = {"schema_version": "1", "application": app_id, "release": "1.0.0", "collection": {"method": "direct", "gaps": [], "unknowns": []},
             "components": {"prompt:system": {"type": "prompt", "fingerprint": "fp1"}, "model:main": {"type": "model", "fingerprint": "fp2"}}}
        s.add(Release(workspace_id=workspace, application_id=app_id, version="1.0.0", manifest=m, manifest_hash="h", collection_gaps=[],
                      collection_status="complete", collected_by="dev"))
    return app_id


def _accepted(workspace: str, app_id: str, phase: str, output: dict, reviewer: str) -> str:
    with tenant_session(workspace) as s:
        row = AiResult(workspace_id=workspace, application_id=app_id, phase=phase, status="accepted", output=output, request={"refs": {}},
                       requested_by="someone-else", reviewer=reviewer)
        s.add(row)
        s.flush()
        return row.id


def test_phase_a_uses_the_declared_purpose_when_no_document_was_added(workspace, generic_app):
    with tenant_session(workspace) as s:
        row = AiResult(workspace_id=workspace, application_id=generic_app, phase="A", status="pending", request={"refs": {}}, requested_by="dev")
        data, ctx = service.build_input(s, row)
    assert list(ctx["sources"]) == [f"declared:{generic_app}"]
    assert "billing questions" in data["sources"][0]["text"] and "prompt:system" in data["sources"][0]["text"]


def test_accepted_proposals_become_one_proposed_plan_that_another_person_activates(workspace, generic_app, people):
    owner, dev, reviewer, viewer = (people[k] for k in ("owner", "developer", "reviewer", "viewer"))
    assert _denied(lambda: ai_routes.build_ai_plan(generic_app, caller=owner)) == "no_accepted_tests"
    _accepted(workspace, generic_app, "A", {"requirements": [{"control": "C01", "statement": "Only signed-in customers may ask.", "spans": []}],
                                           "unknowns": []}, reviewer.username)
    _accepted(workspace, generic_app, "C", {"tests": [
        {"template": "auth_required", "control": "C01", "name": "Anonymous chat is refused", "args": {"request": CHAT}, "severity": "high"},
        {"template": "auth_required", "control": "C01", "name": "Duplicate of the first", "args": {"request": CHAT}},
        {"template": "data_not_disclosed", "control": "C02", "name": "Other tenant sees no invoices",
         "args": {"actor": "other_tenant", "request": CHAT, "markers": ["INV-"]}}], "unknowns": []}, reviewer.username)
    assert _denied(lambda: ai_routes.build_ai_plan(generic_app, caller=viewer)) == "forbidden"
    assert _denied(lambda: ai_routes.build_ai_plan(generic_app, caller=dev)) == "not_assigned"
    routes_handoffs.assign_application_developer(generic_app, dev.username, caller=owner)
    built = ai_routes.build_ai_plan(generic_app, caller=dev)
    plan = built["plan"]
    assert built["status"] == "proposed" and built["source"] == "ai" and built["proposed_by"] == dev.username
    assert plan["tests"] == 3 and plan["controls_tested"] == ["C01", "C02", "C10"] and plan["requirements"] == 1  # duplicate dropped
    assert "C05" in plan["controls_not_assessed"]
    with tenant_session(workspace) as s:
        raw = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == generic_app)).one().profile
    identity = next(t for t in raw["tests"] if t["template"] == "manifest_identity")
    assert identity["mandatory"] and all(t["requires_review"] for t in raw["tests"] if t is not identity)
    assert raw["coverage"]["dependency_edges"]["AI-C01-01"] == ["model:main", "prompt:system"]  # conservative: every component
    decision = routes_onboarding.ProfileDecisionIn(note="Reviewed the AI-built plan")
    assert _denied(lambda: routes_onboarding.activate_profile(generic_app, built["revision"], decision, caller=people["developer"])) == "forbidden"
    activated = routes_onboarding.activate_profile(generic_app, built["revision"], decision, caller=reviewer)
    assert activated["status"] == "active" and activated["reviewed_by"] == reviewer.username


def test_the_proposer_of_a_plan_cannot_activate_it(workspace, generic_app, people):
    owner = people["owner"]
    _accepted(workspace, generic_app, "C", {"tests": [{"template": "auth_required", "control": "C01", "name": "Anonymous chat is refused",
                                                       "args": {"request": CHAT}}], "unknowns": []}, "someone")
    built = ai_routes.build_ai_plan(generic_app, caller=owner)
    decision = routes_onboarding.ProfileDecisionIn(note="Self review")
    assert _denied(lambda: routes_onboarding.activate_profile(generic_app, built["revision"], decision, caller=owner)) == "separation_of_duties"


def test_the_reference_adapter_keeps_its_bundled_tests(workspace, people):
    with tenant_session(workspace) as s:
        s.add(Connection(workspace_id=workspace, application_id=f"{workspace}-app", revision=1, adapter_id="assureops-mcp-reference",
                         adapter_version="0.3.0", config={}, status="verified", created_by="dev"))
    _accepted(workspace, f"{workspace}-app", "C", {"tests": [], "unknowns": []}, "someone")
    assert _denied(lambda: ai_routes.build_ai_plan(f"{workspace}-app", caller=people["owner"])) == "adapter_unsupported"


def test_accepting_c_without_a_profile_keeps_the_proposal_for_the_plan(workspace, generic_app, people):
    from assureops_ai import service as ai_service

    with tenant_session(workspace) as s:
        row = AiResult(workspace_id=workspace, application_id=generic_app, phase="C", status="proposed", request={"refs": {}}, requested_by="dev",
                       output={"tests": [{"template": "auth_required", "control": "C01", "name": "Anonymous chat is refused", "args": {"request": CHAT}}],
                               "unknowns": []})
        s.add(row)
        s.flush()
        effects = ai_service.review(s, row, decision="accept", reviewer=people["reviewer"].username, note="ok")
        assert effects == {"plan_input": True} and row.status == "accepted"
        assert s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == generic_app)).first() is None
    assert ai_routes.build_ai_plan(generic_app, caller=people["owner"])["plan"]["tests"] == 2


def test_declared_facts_complete_proposals_that_could_not_know_them(workspace, generic_app, people):
    owner = people["owner"]
    _accepted(workspace, generic_app, "C", {"tests": [
        {"template": "data_not_disclosed", "control": "C02", "name": "Other tenant sees no invoices", "args": {"actor": "other_tenant", "request": CHAT}},
        {"template": "abstains_when_unsupported", "control": "C09", "name": "Abstains", "args": {"actor": "customer", "request": CHAT}}],
        "unknowns": []}, "someone")
    with pytest.raises(HTTPException) as exc:  # nothing runnable without the facts: say which ones
        ai_routes.build_ai_plan(generic_app, ai_routes.PlanIn(), caller=owner)
    assert exc.value.detail["code"] == "needs_facts" and "markers" in exc.value.detail["message"] and "reply_path" in exc.value.detail["message"]
    built = ai_routes.build_ai_plan(generic_app, ai_routes.PlanIn(facts={"markers": ["INV-"], "unknown_key": "ignored"}), caller=owner)
    plan = built["plan"]
    assert plan["tests"] == 2 and plan["controls_tested"] == ["C02", "C10"] and plan["facts_used"] == ["markers"]
    assert plan["needs_facts"] == [{"result": plan["needs_facts"][0]["result"], "name": "Abstains", "template": "abstains_when_unsupported",
                                    "missing": ["reply_path"]}]  # abstention patterns have a safe default; the reply path does not
    with tenant_session(workspace) as s:
        raw = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == generic_app)).one().profile
    assert next(t for t in raw["tests"] if t["control"] == "C02")["args"]["markers"] == ["INV-"]


def test_phase_c_proposals_may_leave_out_declared_facts_but_nothing_else():
    from assureops_ai import validation

    ctx = {"actors": ["customer"], "templates": []}
    assert validation.c_test_problem({"template": "data_not_disclosed", "control": "C02", "name": "n",
                                      "args": {"actor": "customer", "request": CHAT}}, ctx) is None
    assert "request" in validation.c_test_problem({"template": "data_not_disclosed", "control": "C02", "name": "n",
                                                   "args": {"actor": "customer", "markers": ["X"]}}, ctx)
