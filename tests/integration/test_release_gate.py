"""Exact-SHA release gate, expiring receipts invalidated by incidents/profile changes, signed GitHub webhooks."""

import asyncio
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi import HTTPException

from assureops_api import routes_delivery as rd
from assureops_api.auth import Service
from assureops_domain import connections, evidence_store
from assureops_domain.config import settings
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    Application, Assessment, GithubDelivery, Incident, JobStep, Release, RepositoryRoute, TestRun,
)
from assureops_domain.profile import canonical_hash, normalize, profile_version

SHA = "a" * 40
OTHER = "b" * 40


def minimal_profile():
    return {"profile_id": "gate-test", "version": "1.0.0", "catalog": "agentops-controls-v1", "adapter": "assureops-http-json-v1",
            "requirements": {"self_approval_allowed": False}, "gate_policy": {"version": "1", "blocking_severities": ["critical", "high"]},
            "evidence_freshness_days": 30,
            "tests": [{"id": "ID-1", "control": "C10", "severity": "high", "trials": 1, "name": "identity", "expected": "same release",
                       "template": "manifest_identity", "args": {}, "mandatory": True}]}


@pytest.fixture
def ready_app(workspace):
    app_id = f"{workspace}-app"
    with tenant_session(workspace) as s:
        app = s.get(Application, app_id)
        row = connections.propose_profile(s, app, minimal_profile(), source="file", actor="dev")
        connections.activate_profile(s, app, row.revision, reviewer="rev", note="ok")
        comps = {"code:target": {"type": "code", "fingerprint": "f1"}}
        release = Release(workspace_id=workspace, application_id=app_id, version="R1", manifest={"components": comps, "release": "R1"},
                          manifest_hash=canonical_hash(comps), collection_gaps=[], collection_status="complete", collected_by="t", source_commit=SHA)
        s.add(release)
        s.flush()
        p = normalize(row.profile, row.revision)
        job = Assessment(workspace_id=workspace, application_id=app_id, release_id=release.id, scope="full", plan_id="p", plan={},
                         profile_version=profile_version(p), edge_revision="e", requested_by="t", status="completed")
        s.add(job)
        s.flush()
        step = JobStep(workspace_id=workspace, assessment_id=job.id, step_key=f"{job.id}:ID-1", test_id="ID-1", position=0, status="done")
        s.add(step)
        s.flush()
        art = evidence_store.put_json(s, workspace, {"gate-test": workspace, "nonce": uuid.uuid4().hex})
        s.add(TestRun(workspace_id=workspace, application_id=app_id, release_id=release.id, assessment_id=job.id, step_id=step.id, test_id="ID-1",
                      control_id="C10", outcome="passed", trials=1, passed_trials=1, trial_outcomes=[True], dependency_fingerprints={},
                      profile_version=profile_version(p), artifact_id=art.id, expected="same", observation_source="t",
                      test_digest=p["tests_by_id"]["ID-1"]["digest"]))
    return Service("ci", workspace, app_id, "staging")


def test_unassessed_commit_is_denied(ready_app):
    out = rd.gate_check(rd.GateIn(commit_sha=OTHER), svc_=ready_app)
    assert out["decision"] == "deny" and out["receipt"] is None and "no assessed release" in out["reasons"][0]


def test_ready_commit_gets_receipt_and_new_incident_invalidates_it(ready_app):
    out = rd.gate_check(rd.GateIn(commit_sha=SHA), svc_=ready_app)
    assert out["decision"] == "allow", out["reasons"]
    receipt = out["receipt"]
    ok = rd.verify_receipt(rd.VerifyIn(receipt_id=receipt["id"], signature=receipt["signature"], commit_sha=SHA), svc_=ready_app)
    assert ok["valid"]
    wrong_commit = rd.verify_receipt(rd.VerifyIn(receipt_id=receipt["id"], signature=receipt["signature"], commit_sha=OTHER), svc_=ready_app)
    assert not wrong_commit["valid"] and "different commit" in " ".join(wrong_commit["problems"])
    tampered = rd.verify_receipt(rd.VerifyIn(receipt_id=receipt["id"], signature="0" * 64, commit_sha=SHA), svc_=ready_app)
    assert "signature invalid" in tampered["problems"]
    with tenant_session(ready_app.workspace_id) as s:
        s.add(Incident(workspace_id=ready_app.workspace_id, application_id=ready_app.application_id, control_id="C10", severity="critical",
                       title="t", release="R1", cohort="R1", event_revisions=[], finding_id="none"))
    after = rd.verify_receipt(rd.VerifyIn(receipt_id=receipt["id"], signature=receipt["signature"], commit_sha=SHA), svc_=ready_app)
    assert not after["valid"] and any("incident" in p for p in after["problems"])


def _webhook(body: dict, secret: str | None, delivery: str):
    raw = json.dumps(body).encode()

    class Req:
        async def body(self):
            return raw

    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest() if secret else "sha256=bad"
    return asyncio.run(rd.github_webhook(Req(), x_hub_signature_256=sig, x_github_event="push", x_github_delivery=delivery))


def test_webhook_rejects_bad_signature_and_dedupes(ready_app):
    secret = settings().github_webhook_secret
    if not secret:
        pytest.skip("webhook secret not configured")
    repo = f"acme/{ready_app.application_id}"
    with platform_session() as p:
        p.add(RepositoryRoute(repository=repo, workspace_id=ready_app.workspace_id, application_id=ready_app.application_id))
    delivery = uuid.uuid4().hex
    try:
        with pytest.raises(HTTPException) as exc:
            _webhook({"repository": {"full_name": repo}, "after": SHA}, None, delivery)
        assert exc.value.status_code == 401
        first = _webhook({"repository": {"full_name": repo}, "after": SHA}, secret, delivery)
        assert first["status"] == "evaluated" and first["decision"] == "allow"
        assert _webhook({"repository": {"full_name": repo}, "after": SHA}, secret, delivery)["status"] == "duplicate"
    finally:
        with platform_session() as p:
            p.query(RepositoryRoute).filter_by(repository=repo).delete()
            p.query(GithubDelivery).filter_by(id=delivery).delete()


def test_commit_status_is_posted_for_the_exact_sha(monkeypatch):
    import httpx

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"state": "failure"})

    monkeypatch.setenv("GITHUB_STATUS_TOKEN", "test-status-token")
    out = rd.post_commit_status("acme/app", SHA, "deny", ["gate is incomplete"], transport=httpx.MockTransport(handler))
    assert out["posted"] and out["state"] == "failure"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == f"/repos/acme/app/statuses/{SHA}" and body["context"] == "assureops/release-gate"
    assert seen[0].headers["authorization"] == "Bearer test-status-token"
