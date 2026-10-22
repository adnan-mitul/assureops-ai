"""Notice board and change notifications: the right people hear about changes; internal notes and other tenants stay out."""

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from assureops_api import routes_customer, routes_handoffs
from assureops_domain import connections, notices
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import AppNotice, Application, AssessmentCase, CaseAssignment, Notification, User
from assureops_domain.profile import load_profile_file
from tests.conftest import make_user


def _inbox(username: str) -> list[Notification]:
    with platform_session() as p:
        return list(p.scalars(select(Notification).where(Notification.recipient == username)))


def test_posting_notifies_owners_reviewers_and_assigned_developers_only(workspace, people):
    app_id, owner, dev, reviewer, viewer = f"{workspace}-app", *(people[k] for k in ("owner", "developer", "reviewer", "viewer"))
    routes_handoffs.assign_application_developer(app_id, dev.username, caller=owner)
    posted = routes_customer.post_notice(app_id, routes_customer.NoticeIn(subject="Release 2 on Friday", body="Freeze from Thursday."),
                                         caller=dev)
    assert posted["kind"] == "notice" and posted["author"] == dev.username
    assert any(n.subject.endswith("Release 2 on Friday") for n in _inbox(owner.username))
    assert any(n.kind == "app_notice" for n in _inbox(reviewer.username))
    assert not _inbox(viewer.username) and not [n for n in _inbox(dev.username) if n.kind == "app_notice"]  # viewers and the author: no mail
    board = routes_customer.list_notices(app_id, caller=viewer)  # every member reads the board
    assert [b["subject"] for b in board] == ["Release 2 on Friday"]
    with pytest.raises(HTTPException) as exc:
        routes_customer.post_notice(app_id, routes_customer.NoticeIn(subject="hello", body="x"), caller=viewer)
    assert exc.value.detail["code"] == "forbidden"


def test_unassigned_developer_hears_nothing_and_another_workspace_sees_no_notice(workspace, people):
    app_id = f"{workspace}-app"
    with tenant_session(workspace) as s:
        notices.change(s, s.get(Application, app_id), subject="Release R9 submitted", body="Changed components: prompt:system.")
    assert not [n for n in _inbox(people["developer"].username) if n.kind == "app_change"]  # not assigned to this application
    assert any(n.kind == "app_change" for n in _inbox(people["owner"].username))
    with tenant_session("globex") as s:  # row-level security: the board is tenant data
        assert not s.scalars(select(AppNotice).where(AppNotice.application_id == app_id)).all()


def test_a_proposed_profile_tells_the_team_a_second_person_must_activate(workspace, people):
    app_id = f"{workspace}-app"
    with tenant_session(workspace) as s:
        connections.propose_profile(s, s.get(Application, app_id), load_profile_file("refund-agent"), source="file", actor=people["owner"].username)
    reviewer_mail = [n for n in _inbox(people["reviewer"].username) if n.kind == "app_change"]
    assert reviewer_mail and "waits for activation" in reviewer_mail[0].subject and people["owner"].username in reviewer_mail[0].body


def test_case_messages_reach_the_other_side_and_internal_notes_never_reach_customers(workspace, people):
    staff = make_user(f"analyst-{workspace}@assureops.test", "staff")
    with tenant_session(workspace) as s:
        case = AssessmentCase(workspace_id=workspace, application_id=f"{workspace}-app", title="Q4 review", scope_note="n", created_by="t")
        s.add(case)
        s.flush()
        case_id = case.id
    with platform_session() as p:
        p.add(CaseAssignment(case_id=case_id, workspace_id=workspace, staff_user_id=staff.id, duty="analyst", granted_by="t"))
    try:
        with tenant_session(workspace) as s:
            case = s.get(AssessmentCase, case_id)
            assert notices.case_message(s, case, author=people["owner"].username, author_kind="customer", visibility="customer", body="Logs attached") == 1
            assert notices.case_message(s, case, author=staff.username, author_kind="staff", visibility="internal", body="hypothesis") == 0
            assert notices.case_message(s, case, author=staff.username, author_kind="staff", visibility="customer", body="Please retest") >= 2
        assert [n.kind for n in _inbox(staff.username)] == ["case_message"]
        assert not [n for n in _inbox(people["owner"].username) if "hypothesis" in n.body]
    finally:
        with platform_session() as p:
            p.execute(delete(CaseAssignment).where(CaseAssignment.case_id == case_id))
            p.execute(delete(Notification).where(Notification.recipient == staff.username))
            p.execute(delete(User).where(User.id == staff.id))
