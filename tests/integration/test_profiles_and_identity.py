"""Per-application profiles, unassessed controls, release identity, reuse predicate, publication drift, vault."""

import copy
import json

import pytest
from sqlalchemy.exc import IntegrityError

from assureops_domain import connections, reducer, vault
from assureops_domain.db import tenant_session
from assureops_domain.models import Application, ApplicationProfile, Artifact, Assessment, JobStep, Release, TestRun
from assureops_domain.profile import ProfileError, canonical_hash, for_application, load_profile_file, normalize, profile_version
from tests.conftest import add_release, prof


def lab_profile():
    return load_profile_file("refunddesk-demo")


def test_unassessed_controls_are_visible_and_never_supported(workspace):
    app_id = f"{workspace}-app"
    with tenant_session(workspace) as s:
        app = s.get(Application, app_id)
        row = connections.propose_profile(s, app, lab_profile(), source="file", actor="dev")
        connections.activate_profile(s, app, row.revision, reviewer="rev", note="reviewed")
    release = add_release(workspace, "R1")
    with tenant_session(workspace) as s:
        p = for_application(s, app_id)
        state = reducer.readiness(s, app_id, release, p)
    unassessed = {c["id"] for c in state["controls"] if c["result"] == "unassessed"}
    not_applicable = {c["id"] for c in state["controls"] if c["result"] == "not_applicable"}
    assert unassessed == {"C06", "C07"} and not_applicable == {"C04", "C05", "C09"} == set(state["gate"]["not_applicable"])
    assert unassessed | not_applicable == set(state["gate"]["unassessed"])  # both stay visible as outside the tested scope
    assert all(c["applicability"]["reviewed"] for c in state["controls"] if c["id"] in unassessed | not_applicable)
    assert state["scores"]["controls_assessed"] == 5 and state["gate"]["scope_limited"]
    assert "not assessed" in state["gate"]["reason"]
    assert state["scores"]["evidence_coverage_pct"] == 0  # nothing tested yet; unassessed never adds coverage


def test_proposer_cannot_activate_own_profile(workspace):
    with tenant_session(workspace) as s:
        app = s.get(Application, f"{workspace}-app")
        row = connections.propose_profile(s, app, lab_profile(), source="analyst", actor="dev")
        with pytest.raises(connections.OnboardingError) as exc:
            connections.activate_profile(s, app, row.revision, reviewer="dev", note="mine")
        assert exc.value.code == "separation_of_duties"


def test_invalid_profiles_are_rejected():
    bad = lab_profile()
    bad["tests"][0]["control"] = "C99"
    with pytest.raises(ProfileError):
        normalize(bad)
    dup = lab_profile()
    dup["tests"].append(copy.deepcopy(dup["tests"][0]))
    with pytest.raises(ProfileError):
        normalize(dup)


def test_profile_with_unknown_template_cannot_be_proposed(workspace):
    raw = lab_profile()
    raw["tests"][1]["template"] = "execute_python"
    with tenant_session(workspace) as s:
        app = s.get(Application, f"{workspace}-app")
        with pytest.raises(connections.OnboardingError):
            connections.propose_profile(s, app, raw, source="ai", actor="model")


def test_identical_components_with_different_versions_are_distinct_releases(workspace):
    r1 = add_release(workspace, "R1")
    r1b = add_release(workspace, "R1-hotfix-label")  # same components, new version: must not collapse into R1
    assert r1.manifest_hash == r1b.manifest_hash and r1.id != r1b.id
    with pytest.raises(IntegrityError):
        add_release(workspace, "R1")  # exact identity (version + components) stays unique


def _run(ws, release, test_id, digest):
    p = prof()
    with tenant_session(ws) as s:
        job = Assessment(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, scope="full", plan_id="p", plan={},
                         profile_version=profile_version(p), edge_revision="e", requested_by="test", status="completed")
        s.add(job)
        s.flush()
        step = JobStep(workspace_id=ws, assessment_id=job.id, step_key=f"{job.id}:{test_id}", test_id=test_id, position=0, status="done")
        art = Artifact(workspace_id=ws, sha256=f"sha-{job.id}", size=1, content_type="application/json", storage_key="missing")
        s.add_all([step, art])
        s.flush()
        edges = reducer.accepted_edges(s, f"{ws}-app", p)[test_id]
        run = TestRun(workspace_id=ws, application_id=f"{ws}-app", release_id=release.id, assessment_id=job.id, step_id=step.id, test_id=test_id,
                      control_id=p["tests_by_id"][test_id]["control"], outcome="passed", trials=1, passed_trials=1, trial_outcomes=[True],
                      dependency_fingerprints=reducer.dependency_fingerprints(release, edges), profile_version=profile_version(p),
                      artifact_id=art.id, expected="x", observation_source="test", test_digest=digest)
        s.add(run)
        s.flush()
        return run


def test_changed_test_definition_blocks_reuse(workspace):
    p = prof()
    r1 = add_release(workspace, "R1")
    r2 = add_release(workspace, "R2", {"policy:permission": "fp-new"})
    with tenant_session(workspace) as s:
        edges = reducer.accepted_edges(s, f"{workspace}-app", p)
    mapped = {c for comps in edges.values() for c in comps}
    good = _run(workspace, r1, "T-C09-02", p["tests_by_id"]["T-C09-02"]["digest"])
    old = _run(workspace, r1, "T-C09-02", "different-definition")
    assert reducer._reusable(good, r1, r2, edges["T-C09-02"], p["tests_by_id"]["T-C09-02"], mapped, p)
    assert not reducer._reusable(old, r1, r2, edges["T-C09-02"], p["tests_by_id"]["T-C09-02"], mapped, p)


def test_vault_encrypts_and_never_describes_values(workspace):
    with tenant_session(workspace) as s:
        row = vault.store(s, workspace_id=workspace, application_id=f"{workspace}-app", name="actor", value="super-secret-token", actor="dev")
        assert "super-secret-token" not in row.ciphertext
        assert "super-secret-token" not in json.dumps(vault.describe(row), default=str)
        assert vault.reveal(s, row.id) == "super-secret-token"
        vault.revoke(s, row.id, "owner")
        with pytest.raises(vault.VaultError):
            vault.reveal(s, row.id)


def test_profile_activation_supersedes_previous(workspace):
    with tenant_session(workspace) as s:
        app = s.get(Application, f"{workspace}-app")
        row = connections.propose_profile(s, app, lab_profile(), source="file", actor="dev")
        connections.activate_profile(s, app, row.revision, reviewer="rev", note="ok")
        states = {r.revision: r.status for r in s.query(ApplicationProfile).filter_by(application_id=app.id)}
    assert states == {1: "superseded", row.revision: "active"}
