"""Integration fixtures: each test gets its own throwaway workspace in the real database."""

import uuid

import pytest
from sqlalchemy import delete

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    AiResult, AnalysisRun, Application, ApplicationProfile, Approval, Assessment, Connection, ConnectorSecret, CoverageContract, DependencyEdge,
    DeploymentReceipt, EventSource, Finding,
    Incident, JobStep, LogicalAction, ModelCall, Release, RuntimeEvent, SourceDocument, TestRun, Workspace,
)
from assureops_domain.profile import canonical_hash, load_coverage_contract, load_profile_file, normalize


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
        for model in (Incident, Finding, DeploymentReceipt, AnalysisRun, TestRun, JobStep, Assessment, LogicalAction, Approval, RuntimeEvent, Release,
                      DependencyEdge, AiResult,
                      ModelCall, SourceDocument, Connection, ConnectorSecret, CoverageContract, ApplicationProfile, Application):
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
