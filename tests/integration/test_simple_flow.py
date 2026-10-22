"""Simple flow: customer submits a GitHub link and live URL; an AssureOps developer plans; an AssureOps admin approves."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select

from assureops_api import routes_simple, routes_staff
from assureops_api.auth import Caller
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    Application, ApplicationProfile, CaseAssignment, Connection, Release, RepositoryBinding, RepositoryRoute, StaffRole, User,
)
from tests.conftest import make_user


def _submission(**kw) -> routes_simple.SubmissionIn:
    return routes_simple.SubmissionIn(**{"name": "Support Bot", "purpose": "Answers billing questions for signed-in customers.",
                                         "repository": f"https://github.com/acme/support-bot-{uuid.uuid4().hex[:6]}.git",
                                         "base_url": "http://127.0.0.1:9", "environment": "production", "chat_path": "/chat",
                                         "test_token": "synthetic-test-token", **kw})


@pytest.fixture
def staff():
    tag = uuid.uuid4().hex[:6]
    made = {"developer": make_user(f"dev-{tag}@assureops.test", "staff"), "admin": make_user(f"admin-{tag}@assureops.test", "staff")}
    roles = {"developer": "analyst", "admin": "senior_reviewer"}
    with platform_session() as p:
        for k, u in made.items():
            p.add(StaffRole(user_id=u.id, role=roles[k]))
    yield {k: Caller(u.id, u.username, u.display_name, "staff", staff_roles={roles[k]}) for k, u in made.items()}
    with platform_session() as p:
        ids = [u.id for u in made.values()]
        p.execute(delete(CaseAssignment).where(CaseAssignment.staff_user_id.in_(ids)))
        p.execute(delete(StaffRole).where(StaffRole.user_id.in_(ids)))
        p.execute(delete(User).where(User.id.in_(ids)))


def test_submission_rejects_what_cannot_be_tested():
    with pytest.raises(ValidationError):
        _submission(repository="https://gitlab.com/acme/bot")
    with pytest.raises(ValidationError):
        _submission(base_url="https://staging.example.com/app")  # an origin, not a page
    assert _submission(repository="Acme/Bot").repository == "acme/bot"


def test_customer_submits_developer_plans_admin_approves(workspace, people, staff):
    owner = people["owner"]
    with pytest.raises(HTTPException) as exc:
        routes_simple.submit(_submission(), caller=people["developer"])
    assert exc.value.detail["code"] == "forbidden"  # the customer's owner submits
    out = routes_simple.submit(_submission(), caller=owner)
    app_id, case_id = out["application_id"], out["case_id"]
    try:
        with tenant_session(workspace) as s:
            app = s.get(Application, app_id)
            conn = s.scalars(select(Connection).where(Connection.application_id == app_id)).one()
            assert app.environment == "production" and conn.config["base_url"] == "http://127.0.0.1:9"
            assert "user" in conn.config["actors"] and "synthetic-test-token" not in str(conn.config)  # the token is in the vault only
            assert "/chat" in conn.config["scope"]["allowed_paths"]
            assert s.scalars(select(RepositoryBinding).where(RepositoryBinding.application_id == app_id)).one().repository.startswith("acme/")
        listed = routes_simple.my_submissions(caller=people["viewer"])
        assert listed[0]["case_id"] == case_id and listed[0]["state"] == "submitted" and listed[0]["report_id"] is None

        with platform_session() as p:
            for duty, who in (("analyst", "developer"), ("reviewer", "admin")):
                p.add(CaseAssignment(case_id=case_id, workspace_id=workspace, staff_user_id=staff[who].user_id, duty=duty, granted_by="t"))
        with pytest.raises(HTTPException) as exc:
            routes_simple.staff_baseline(case_id, caller=staff["developer"])
        assert exc.value.detail["code"] == "not_prepared"
        with tenant_session(workspace) as s:  # what "Verify and collect" records when the application answers
            m = {"schema_version": "1", "application": app_id, "release": "1.0.0", "collection": {"method": "direct", "gaps": [], "unknowns": []},
                 "components": {"prompt:system": {"type": "prompt", "fingerprint": "a"}, "model:main": {"type": "model", "fingerprint": "b"}}}
            s.add(Release(workspace_id=workspace, application_id=app_id, version="1.0.0", manifest=m, manifest_hash="h", collection_gaps=[],
                          collection_status="complete", collected_by="t"))
        plan = routes_simple.staff_baseline(case_id, caller=staff["developer"])
        assert plan["status"] == "proposed" and plan["proposed_by"] == staff["developer"].username and len(plan["tests"]) >= 3
        with pytest.raises(HTTPException) as exc:  # the admin duty belongs to the other person
            routes_simple.staff_baseline(case_id, caller=staff["admin"])
        decision = routes_staff.StaffProfileDecisionIn(revision=plan["revision"], decision="activate", note="Reviewed the baseline plan")
        with pytest.raises(HTTPException):
            routes_staff.staff_review_profile(case_id, decision, caller=staff["developer"])
        assert routes_staff.staff_review_profile(case_id, decision, caller=staff["admin"])["status"] == "active"
    finally:
        with platform_session() as p:
            p.execute(delete(RepositoryRoute).where(RepositoryRoute.application_id == app_id))
        with tenant_session(workspace) as s:
            s.execute(delete(ApplicationProfile).where(ApplicationProfile.application_id == app_id))
            s.execute(delete(RepositoryBinding).where(RepositoryBinding.application_id == app_id))
