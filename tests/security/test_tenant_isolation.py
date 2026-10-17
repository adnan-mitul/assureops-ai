"""T02: workspace isolation enforced by row-level security with the real runtime role."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Application


def test_runtime_role_cannot_bypass_rls():
    with platform_session() as s:
        row = s.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    assert row == (False, False)


def test_other_workspace_rows_are_invisible(workspace):
    with tenant_session("acme") as s:
        assert s.get(Application, f"{workspace}-app") is None
        assert all(a.workspace_id == "acme" for a in s.scalars(select(Application)))
    with tenant_session(workspace) as s:
        assert [a.id for a in s.scalars(select(Application))] == [f"{workspace}-app"]


def test_no_tenant_context_sees_nothing(workspace):
    with platform_session() as s:
        assert s.scalars(select(Application)).all() == []


def test_cannot_write_into_another_workspace(workspace):
    with pytest.raises(ProgrammingError):
        with tenant_session("acme") as s:
            s.add(Application(id="smuggled", workspace_id=workspace, name="x", environment="staging", mode="observe_only",
                              target_url="http://x", tools_url="http://x"))
            s.flush()
