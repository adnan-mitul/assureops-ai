"""Application-scoped developer grants, revocation on the next request, staff administration and internal-note confinement."""

import uuid

import pytest
from sqlalchemy import delete, select

from assureops_api import auth, routes_admin, routes_customer, routes_handoffs, routes_staff
from assureops_api.access import require_application_writer
from assureops_api.auth import Caller
from assureops_domain import grants, handoffs
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    ApplicationGrant, AssessmentCase, CaseAssignment, CaseIndex, CaseMessage, Invitation, Membership, Notification, StaffRole, User, now,
)
from fastapi import HTTPException
from tests.conftest import make_user as _user


def _denied(fn) -> str:
    with pytest.raises(HTTPException) as exc:
        fn()
    return exc.value.detail["code"]


def test_unassigned_developer_cannot_change_the_application(workspace, people):
    app = f"{workspace}-app"
    dev = people["developer"]
    with tenant_session(workspace) as s:
        assert _denied(lambda: require_application_writer(s, dev, app)) == "not_assigned"
    assert _denied(lambda: routes_customer.submit_release(app, caller=dev)) == "not_assigned"
    with tenant_session(workspace) as s:
        require_application_writer(s, people["owner"], app)  # owners reach every application of the workspace
        assert _denied(lambda: require_application_writer(s, people["viewer"], app)) == "forbidden"


def test_assignment_grants_and_revocation_removes_access_on_the_next_request(workspace, people):
    app, dev, owner = f"{workspace}-app", people["developer"], people["owner"]
    routes_handoffs.assign_application_developer(app, dev.username, caller=owner)
    with tenant_session(workspace) as s:
        require_application_writer(s, dev, app)
    listed = routes_handoffs.list_application_developers(app, caller=people["viewer"])
    assert [d["user"] for d in listed if d["active"]] == [dev.username]
    routes_handoffs.unassign_application_developer(app, dev.username, caller=owner)
    with tenant_session(workspace) as s:
        assert _denied(lambda: require_application_writer(s, dev, app)) == "not_assigned"
    with platform_session() as p:
        kinds = {n.kind for n in p.scalars(select(Notification).where(Notification.recipient == dev.username))}
    assert {"application_assigned", "application_unassigned"} <= kinds


def test_expired_assignment_stops_access(workspace, people):
    app, dev = f"{workspace}-app", people["developer"]
    with tenant_session(workspace) as s:
        s.add(ApplicationGrant(workspace_id=workspace, application_id=app, user_id=dev.user_id, granted_by="t", expires_at=now() - 1))
    with tenant_session(workspace) as s:
        assert _denied(lambda: require_application_writer(s, dev, app)) == "not_assigned"


def test_only_owners_assign_and_only_developers_are_assignable(workspace, people):
    app = f"{workspace}-app"
    assert _denied(lambda: routes_handoffs.assign_application_developer(app, people["developer"].username, caller=people["developer"])) == "forbidden"
    assert _denied(lambda: routes_handoffs.assign_application_developer(app, people["viewer"].username, caller=people["owner"])) == "invalid_role"
    assert _denied(lambda: routes_handoffs.assign_application_developer("refund-agent", people["developer"].username, caller=people["owner"])) == "not_found"


def test_removing_a_member_ends_their_assignments_and_their_next_request_is_denied(workspace, people):
    app, dev, owner = f"{workspace}-app", people["developer"], people["owner"]
    routes_handoffs.assign_application_developer(app, dev.username, caller=owner)
    result = routes_handoffs.change_member(dev.username, routes_handoffs.RoleIn(role=None), caller=owner)
    assert result["assignments_ended"] == 1
    reloaded = auth._load_user({"preferred_username": dev.username}, "customer")  # what the next request resolves
    assert workspace not in reloaded.memberships
    with tenant_session(workspace) as s:
        assert grants.active_grant(s, app, dev.user_id) is None


def test_revoked_invitation_cannot_be_accepted(workspace, people):
    created = routes_handoffs.create_invitation(routes_handoffs.InviteIn(email=f"inv-{uuid.uuid4().hex[:6]}@acme.test", role="developer"),
                                                caller=people["owner"])
    with platform_session() as s:  # recover the one-time token the e-mail carried by re-issuing it under test control
        inv = s.get(Invitation, created["id"])
        token = "aoinv_test_" + uuid.uuid4().hex
        inv.token_hash = handoffs.token_hash(token)
    assert routes_handoffs.revoke_invitation(created["id"], caller=people["owner"])["revoked"] is True
    with platform_session() as s:
        with pytest.raises(handoffs.HandoffError) as exc:
            handoffs.accept(s, token=token, username=created["email"], display_name="x")
    assert exc.value.code == "invalid_invitation"


def test_internal_staff_notes_never_reach_customer_reads(workspace, people):
    with tenant_session(workspace) as s:
        case = AssessmentCase(workspace_id=workspace, application_id=f"{workspace}-app", title="t", scope_note="n", created_by="t", state="assessment")
        s.add(case)
        s.flush()
        s.add(CaseMessage(workspace_id=workspace, case_id=case.id, author="analyst", author_kind="staff", visibility="internal",
                          body="INTERNAL-ONLY hypothesis about the customer"))
        s.add(CaseMessage(workspace_id=workspace, case_id=case.id, author="analyst", author_kind="staff", visibility="customer", body="Please send logs"))
        case_id = case.id
    for view in (routes_customer.get_case(case_id, caller=people["viewer"]), *routes_customer.list_cases(caller=people["viewer"])):
        assert "INTERNAL-ONLY" not in str(view)
    assert "Please send logs" in str(routes_customer.get_case(case_id, caller=people["viewer"]))
    with platform_session() as p:
        assert not [n for n in p.scalars(select(Notification).where(Notification.workspace_id == workspace)) if "INTERNAL-ONLY" in n.body]


# ---------------- Staff administration ----------------

@pytest.fixture
def staff_people():
    tag = uuid.uuid4().hex[:6]
    made = {r: _user(f"{r}-{tag}@assureops.test", "staff") for r in ("admin", "analyst", "analyst2", "manager")}
    roles = {"admin": ["admin"], "analyst": ["analyst"], "analyst2": ["analyst"], "manager": ["case_manager"]}
    with platform_session() as s:
        for key, u in made.items():
            for r in roles[key]:
                s.add(StaffRole(user_id=u.id, role=r))
    callers = {k: Caller(u.id, u.username, u.display_name, "staff", staff_roles=set(roles[k])) for k, u in made.items()}
    yield callers
    with platform_session() as s:
        ids = [u.id for u in made.values()]
        s.execute(delete(CaseAssignment).where(CaseAssignment.staff_user_id.in_(ids)))
        s.execute(delete(StaffRole).where(StaffRole.user_id.in_(ids)))
        s.execute(delete(Notification).where(Notification.recipient.in_([u.username for u in made.values()])))
        s.execute(delete(User).where(User.id.in_(ids)))


def test_staff_roles_are_managed_by_another_admin_only(staff_people):
    admin, analyst = staff_people["admin"], staff_people["analyst"]
    assert _denied(lambda: routes_admin.grant_staff_role(analyst.username, "senior_reviewer", caller=analyst)) == "forbidden"
    assert _denied(lambda: routes_admin.grant_staff_role(admin.username, "operator", caller=admin)) == "self_grant"
    assert _denied(lambda: routes_admin.grant_staff_role(analyst.username, "superuser", caller=admin)) == "invalid_role"
    assert routes_admin.grant_staff_role(analyst.username, "senior_reviewer", caller=admin)["active"] is True
    assert routes_admin.revoke_staff_role(analyst.username, "senior_reviewer", caller=admin)["active"] is False
    listed = {row["user"]: row for row in routes_admin.list_staff(caller=admin)["staff"]}
    assert any(h["role"] == "senior_reviewer" and h["revoked_by"] == admin.username for h in listed[analyst.username]["history"])


def test_last_admin_cannot_be_removed(staff_people):
    admin, manager = staff_people["admin"], staff_people["manager"]
    with platform_session() as s:  # make this fixture's admin the only active one for the duration of the check
        others = s.scalars(select(StaffRole).where(StaffRole.role == "admin", StaffRole.active.is_(True), StaffRole.user_id != admin.user_id)).all()
        for r in others:
            r.active = False
        other_ids = [r.id for r in others]
    try:
        routes_admin.grant_staff_role(manager.username, "admin", caller=admin)
        manager.staff_roles.add("admin")
        routes_admin.revoke_staff_role(admin.username, "admin", caller=manager)  # two admins: removing one is allowed
        with platform_session() as s:
            with pytest.raises(handoffs.HandoffError) as exc:  # now the manager is the only admin left
                grants.set_staff_role(s, username=manager.username, role="admin", active=False, actor_id=admin.user_id, actor=admin.username)
        assert exc.value.code == "last_admin"
    finally:
        with platform_session() as s:
            for r in s.scalars(select(StaffRole).where(StaffRole.id.in_(other_ids))):
                r.active = True


def test_revoked_role_or_assignment_ends_case_access_and_reassignment_keeps_duties_separate(workspace, staff_people):
    admin, analyst, analyst2, manager = (staff_people[k] for k in ("admin", "analyst", "analyst2", "manager"))
    with tenant_session(workspace) as s:
        case = AssessmentCase(workspace_id=workspace, application_id=f"{workspace}-app", title="t", scope_note="n", created_by="t", state="assessment")
        s.add(case)
        s.flush()
        case_id = case.id
    with platform_session() as s:
        s.add(CaseIndex(case_id=case_id, workspace_id=workspace, workspace_name="t", application_name="a", title="t", state="assessment", priority="normal"))
        s.add(CaseAssignment(case_id=case_id, workspace_id=workspace, staff_user_id=analyst.user_id, duty="analyst", granted_by="t"))
    try:
        assert routes_staff.assignment(analyst, case_id, "analyst").duty == "analyst"
        routes_staff.reassign(case_id, routes_staff.ReassignIn(duty="analyst", from_user=analyst.username, to_user=analyst2.username), caller=manager)
        assert _denied(lambda: routes_staff.assignment(analyst, case_id)) == "not_assigned"
        assert routes_staff.assignment(analyst2, case_id, "analyst")
        assert _denied(lambda: routes_staff.reassign(case_id, routes_staff.ReassignIn(duty="analyst", from_user=analyst2.username,
                                                                                       to_user=admin.username), caller=manager)) == "missing_role"
        ended = routes_admin.revoke_staff_role(analyst2.username, "analyst", caller=admin)["assignments_ended"]
        assert ended == 1
        reloaded = auth._load_user({"preferred_username": analyst2.username}, "staff")
        assert "analyst" not in reloaded.staff_roles
        analyst2.staff_roles.discard("analyst")
        assert _denied(lambda: routes_staff.assignment(analyst2, case_id)) == "not_assigned"
        load = {r["user"]: r for r in routes_admin.workload(caller=manager)["staff"]}
        assert load[analyst2.username]["analyst_cases"] == 0
    finally:
        with platform_session() as s:
            s.execute(delete(CaseAssignment).where(CaseAssignment.case_id == case_id))
            s.execute(delete(CaseIndex).where(CaseIndex.case_id == case_id))
