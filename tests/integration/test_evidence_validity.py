"""T11/T12: change impact, conservative fallback and the reuse predicate."""

from assureops_domain import reducer
from assureops_domain.db import tenant_session
from assureops_domain.models import Artifact, Assessment, DependencyEdge, JobStep, TestRun
from assureops_domain.profile import load_coverage_contract, profile_version
from tests.conftest import add_release, prof


def test_policy_change_invalidates_only_dependent_tests(workspace):
    r1 = add_release(workspace, "R1")
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})
    with tenant_session(workspace) as s:
        result = reducer.compare(s, f"{workspace}-app", r1, r2, prof())
    edges = load_coverage_contract("refund-agent.mcp-reference")["dependency_edges"]
    expected = {t for t, comps in edges.items() if "policy:permission" in comps} | {"T-C10-01"}
    assert {r["test_id"] for r in result["retest"]} == expected
    assert not result["conservative_fallback"]
    assert "T-C09-02" in result["reusable"]  # its reviewed edges do not include the permission policy


def test_unmapped_change_forces_full_retest(workspace):
    r1 = add_release(workspace, "R1")
    r2 = add_release(workspace, "R2", {"tool:get_action_status": "fp-changed"})
    with tenant_session(workspace) as s:
        result = reducer.compare(s, f"{workspace}-app", r1, r2, prof())
    assert result["conservative_fallback"] and result["unmapped"] == ["tool:get_action_status"]
    assert len(result["retest"]) == len(prof()["tests"]) and result["reusable"] == []


def test_removed_component_counts_as_change(workspace):
    r1 = add_release(workspace, "R1")
    r2 = add_release(workspace, "R2", {"corpus:docs": None})
    assert {c["component"]: c["change"] for c in reducer.diff_components(r1, r2)} == {"corpus:docs": "removed"}


def _run(ws, release, test_id, outcome="passed", fingerprints=None):
    with tenant_session(ws) as s:
        job = Assessment(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, scope="full", plan_id="p", plan={},
                         profile_version=profile_version(prof()), edge_revision="e", requested_by="test", status="completed")
        s.add(job)
        s.flush()
        step = JobStep(workspace_id=ws, assessment_id=job.id, step_key=f"{job.id}:{test_id}", test_id=test_id, position=0, status="done")
        art = Artifact(workspace_id=ws, sha256=f"sha-{job.id}", size=1, content_type="application/json", storage_key="missing")
        s.add_all([step, art])
        s.flush()
        edges = reducer.accepted_edges(s, f"{ws}-app", prof())[test_id]
        run = TestRun(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, assessment_id=job.id, step_id=step.id, test_id=test_id,
                      control_id=prof()["tests_by_id"][test_id]["control"], outcome=outcome, trials=1, passed_trials=int(outcome == "passed"),
                      trial_outcomes=[outcome == "passed"], dependency_fingerprints=fingerprints or reducer.dependency_fingerprints(release, edges),
                      profile_version=profile_version(prof()), artifact_id=art.id, expected="x", observation_source="test")
        s.add(run)
        s.flush()
        return run


def test_changed_dependency_makes_prior_support_stale_and_preserves_failures(workspace):
    r1 = add_release(workspace, "R1")
    _run(workspace, r1, "T-C03-01", "passed")
    _run(workspace, r1, "T-C09-01", "passed")
    _run(workspace, r1, "T-C04-01", "failed")
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})
    with tenant_session(workspace) as s:
        state = reducer.readiness(s, f"{workspace}-app", r2, prof())
    tests = {t["test_id"]: t for t in state["tests"]}
    assert tests["T-C03-01"]["validity"] in ("stale", "unavailable") and tests["T-C03-01"]["result"] == "supported"
    assert tests["T-C04-01"]["result"] == "failed"  # an existing failure is never hidden by staleness
    assert state["gate"]["status"] == "blocked"


def test_rejected_edge_invalidates_reuse(workspace):
    r1 = add_release(workspace, "R1")
    run = _run(workspace, r1, "T-C09-02", "passed")
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})  # does not touch T-C09-02's edges
    with tenant_session(workspace) as s:
        releases = {r1.id: r1}
        edges = reducer.accepted_edges(s, f"{workspace}-app", prof())
        mapped = {c for comps in edges.values() for c in comps}
        assert reducer._reusable(run, releases[r1.id], r2, edges["T-C09-02"], prof()["tests_by_id"]["T-C09-02"], mapped, prof())
        edge = s.query(DependencyEdge).filter_by(test_id="T-C09-02", component_id="corpus:docs").one()
        edge.status = "rejected"
        s.flush()
        edges = reducer.accepted_edges(s, f"{workspace}-app", prof())
        assert not reducer._reusable(run, releases[r1.id], r2, edges["T-C09-02"], prof()["tests_by_id"]["T-C09-02"], mapped, prof())


def test_scores_follow_plan_definitions(workspace):
    r1 = add_release(workspace, "R1")
    with tenant_session(workspace) as s:
        state = reducer.readiness(s, f"{workspace}-app", r1, prof())
    assert state["scores"]["evidence_coverage_pct"] == 0 and state["scores"]["evidence_support_pct"] == 0
    assert state["gate"]["status"] == "incomplete"
