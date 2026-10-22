"""Integration fixtures: each test gets its own throwaway workspace in the real database."""

import os
import uuid

import pytest
from sqlalchemy import delete

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    AiResult, AnalysisRun, AppNotice, Application, ApplicationGrant, ApplicationProfile, Approval, Assessment, AssessmentCase, CaseMessage, Connection, ConnectorSecret, CoverageContract, DependencyEdge,
    DeploymentReceipt, EventSource, Finding, Invitation, Membership, Notification, RiskAcceptance, User,
    Incident, JobStep, LogicalAction, ModelCall, Release, RuntimeEvent, SourceDocument, TestRun, Workspace,
)
from assureops_domain.profile import canonical_hash, load_coverage_contract, load_profile_file, normalize


# Tests never reach a real mail provider: the local dev.env may hold a Resend key or SMTP settings.
for _transport in ("RESEND_API_KEY", "NOTIFY_SMTP_HOST", "NOTIFY_WEBHOOK_URL"):
    os.environ[_transport] = ""

def prof() -> dict:
    """The reference profile exactly as the reducer sees it for the fixture application (active revision 1)."""
    return normalize(load_profile_file("refund-agent"), 1)


def manifest(release: str, overrides: dict | None = None) -> dict:
    contract = load_coverage_contract("refund-agent.mcp-reference")
    components = {c: {"type": c.split(":")[0], "fingerprint": f"fp-{c}"} for comps in contract["dependency_edges"].values() for c in comps}
    components["tool:get_action_status"] = {"type": "tool", "fingerprint": "fp-status"}
    for cid, fp in (overrides or {}).items():
        if fp is None:
            components.pop(cid, None)
        else:
            components[cid] = {"type": cid.split(":")[0], "fingerprint": fp}
    return {"schema_version": "1", "application": "app", "release": release, "components": components,
            "policy_versions": {"permission": "1.0"}, "collection": {"method": "direct", "gaps": [], "unknowns": []}}


@pytest.fixture
def workspace():
    ws = f"t-{uuid.uuid4().hex[:10]}"
    with platform_session() as s:
        s.add(Workspace(id=ws, name=f"Test {ws}"))
    with tenant_session(ws) as s:
        s.add(Application(id=f"{ws}-app", workspace_id=ws, name="Test app", environment="staging", mode="enforce_supported_actions",
                          target_url="http://127.0.0.1:9", tools_url="http://127.0.0.1:9/mcp"))
        s.flush()
        raw = load_profile_file("refund-agent")
        s.add(ApplicationProfile(workspace_id=ws, application_id=f"{ws}-app", revision=1, profile=raw, digest=canonical_hash(raw), status="active",
                                 source="file", proposed_by="fixture", reviewed_by="fixture-reviewer"))
        for test_id, comps in load_coverage_contract("refund-agent.mcp-reference")["dependency_edges"].items():
            for cid in comps:
                s.add(DependencyEdge(workspace_id=ws, application_id=f"{ws}-app", test_id=test_id, component_id=cid, status="accepted",
                                     source="coverage_contract", reviewer="test"))
    yield ws
    with tenant_session(ws) as s:
        for model in (RiskAcceptance, Incident, Finding, DeploymentReceipt, AnalysisRun, TestRun, JobStep, Assessment, LogicalAction, Approval, RuntimeEvent, Release,
                      DependencyEdge, AiResult, AppNotice,
                      ModelCall, SourceDocument, Connection, ConnectorSecret, CoverageContract, ApplicationProfile, ApplicationGrant,
                      CaseMessage, AssessmentCase, Application):
            s.execute(delete(model))
    with platform_session() as s:
        s.execute(delete(EventSource).where(EventSource.workspace_id == ws))
        s.execute(delete(Workspace).where(Workspace.id == ws))


def add_release(ws: str, version: str, overrides: dict | None = None) -> Release:
    m = manifest(version, overrides)
    with tenant_session(ws) as s:
        release = Release(workspace_id=ws, application_id=f"{ws}-app", version=version, manifest=m, manifest_hash=canonical_hash(m["components"]),
                          collection_gaps=[], collection_status="complete", collected_by="test")
        s.add(release)
        s.flush()
        return release


def make_user(username: str, kind: str = "customer") -> User:
    with platform_session() as s:
        u = User(username=username, display_name=username.split("@")[0], kind=kind)
        s.add(u)
        s.flush()
        s.expunge(u)
        return u


@pytest.fixture
def people(workspace):
    tag = uuid.uuid4().hex[:6]
    made = {role: make_user(f"{role}-{tag}@acme.test") for role in ("owner", "developer", "reviewer", "viewer")}
    with platform_session() as s:
        for role, u in made.items():
            s.add(Membership(workspace_id=workspace, user_id=u.id, role=role))
    from assureops_api.auth import Caller

    callers = {role: Caller(u.id, u.username, u.display_name, "customer", workspace_id=workspace, role=role, memberships={workspace: role})
               for role, u in made.items()}
    yield callers
    with platform_session() as s:
        ids = [u.id for u in made.values()]
        s.execute(delete(Membership).where(Membership.user_id.in_(ids)))
        s.execute(delete(Notification).where(Notification.workspace_id == workspace))
        s.execute(delete(Invitation).where(Invitation.workspace_id == workspace))
        s.execute(delete(User).where(User.id.in_(ids)))
