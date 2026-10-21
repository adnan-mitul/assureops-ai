"""Private connector (relay): encrypted one-time capsules, application-bound claims, nonce-bound results, deadlines, end to end."""

import hashlib
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from assureops_api.auth import token_hash
from assureops_api.main import app
from assureops_connectors.relay import Relay
from assureops_domain import connections, relay
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Application, Connection, RelayTask, ServiceCredential, now

SECRET = "relay-test-target-credential"
COMPONENTS = {"code:target": {"type": "code", "fingerprint": "fp-1"}}
MANIFEST = {"schema_version": "1", "application": "private-app", "release": "R1", "components": COMPONENTS, "collection": {"gaps": []}}


class Target(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        body = MANIFEST if self.path == "/manifest" else {"ok": True}
        data = json.dumps(body).encode()
        self.send_response(200 if self.path in ("/manifest", "/health") else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def target():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _credential(ws: str, app_id: str) -> tuple[str, str]:
    token = "aorl_" + secrets.token_urlsafe(16)
    with platform_session() as p:
        cred = ServiceCredential(kind="relay", workspace_id=ws, application_id=app_id, environment="staging", token_hash=token_hash(token))
        p.add(cred)
        p.flush()
        return cred.id, token


@pytest.fixture
def relay_app(workspace):
    cred_id, token = _credential(workspace, f"{workspace}-app")
    yield workspace, cred_id, token
    with tenant_session(workspace) as s:
        s.execute(delete(RelayTask))
    with platform_session() as p:
        p.execute(delete(ServiceCredential).where(ServiceCredential.workspace_id == workspace))


def _capsule(base_url: str) -> dict:
    manifest_hash = hashlib.sha256(json.dumps(COMPONENTS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"adapter_id": "assureops-http-json-v1", "connection_revision": 1, "step_id": "step-relay-1", "release_version": "R1",
            "config": {"base_url": base_url, "manifest_path": "/manifest", "health_path": "/health", "scope": {"allowed_paths": ["/health"]},
                       "execution": {"mode": "relay"}},
            "credentials": {"user": SECRET}, "allow_private": True, "frozen_manifest": MANIFEST, "manifest_hash": manifest_hash,
            "run_tokens": ["t1"], "identity_check": True,
            "test": {"id": "ID-1", "control": "C10", "severity": "high", "trials": 1, "name": "identity", "expected": "same release",
                     "template": "manifest_identity", "args": {}, "digest": "d"}}


def test_payload_is_encrypted_and_handed_out_once_to_its_own_application_only(relay_app, target):
    ws, cred_id, _ = relay_app
    with tenant_session(ws) as s:
        task = relay.enqueue(s, workspace_id=ws, application_id=f"{ws}-app", kind="step", ref_id="step-1", payload=_capsule(target), deadline_seconds=60)
        assert SECRET not in task.payload_ciphertext and "base_url" not in task.payload_ciphertext
        task_id = task.id
    with tenant_session(ws) as s:
        assert relay.claim(s, application_id="another-app", credential_id="other") is None  # a credential sees only its application
    with tenant_session(ws) as s:
        claimed = relay.claim(s, application_id=f"{ws}-app", credential_id=cred_id)
        assert claimed["payload"]["credentials"]["user"] == SECRET
    with tenant_session(ws) as s:
        row = s.get(RelayTask, task_id)
        assert row.status == "claimed" and row.payload_ciphertext is None  # wiped after the one claim
        assert relay.claim(s, application_id=f"{ws}-app", credential_id=cred_id) is None
    with tenant_session(ws) as s:
        with pytest.raises(relay.RelayError) as exc:
            relay.complete(s, task_id=task_id, application_id=f"{ws}-app", credential_id=cred_id, nonce="rln_wrong_nonce", result={})
        assert exc.value.code == "bad_nonce"
    with tenant_session(ws) as s:
        relay.complete(s, task_id=task_id, application_id=f"{ws}-app", credential_id=cred_id, nonce=claimed["nonce"], result={"status": "completed"})
    with tenant_session(ws) as s:
        with pytest.raises(relay.RelayError) as exc:  # a result is accepted once
            relay.complete(s, task_id=task_id, application_id=f"{ws}-app", credential_id=cred_id, nonce=claimed["nonce"], result={})
        assert exc.value.code == "not_claimed"


def test_a_missed_deadline_is_an_error_never_a_pass(relay_app, target):
    ws, cred_id, _ = relay_app
    with tenant_session(ws) as s:
        task = relay.enqueue(s, workspace_id=ws, application_id=f"{ws}-app", kind="step", ref_id="step-2", payload=_capsule(target), deadline_seconds=60)
        task.deadline_at = now() - 1
        task_id = task.id
    outcome = relay.wait_for_result(ws, task_id, timeout=1)
    assert outcome["status"] == "error" and "relay_timeout" in outcome["error"]
    with tenant_session(ws) as s:
        assert s.get(RelayTask, task_id).status == "expired" and s.get(RelayTask, task_id).payload_ciphertext is None
        assert relay.claim(s, application_id=f"{ws}-app", credential_id=cred_id) is None


def test_relay_runs_the_sandbox_against_a_private_target_and_reports_through_the_api(relay_app, target):
    ws, cred_id, token = relay_app
    with tenant_session(ws) as s:
        task_id = relay.enqueue(s, workspace_id=ws, application_id=f"{ws}-app", kind="step", ref_id="step-3", payload=_capsule(target),
                                deadline_seconds=120).id
    api = TestClient(app)
    assert TestClient(app).post("/v1/integration/relay/claim", headers={"Authorization": "Bearer aorl_not_a_real_token"}).status_code == 403
    assert Relay("http://testserver", token, client=api).once() == "done"
    with tenant_session(ws) as s:
        row = s.get(RelayTask, task_id)
        assert row.status == "completed" and row.result["status"] == "completed", row.result
        assert row.result["trials"][0]["passed"] is True
        assert SECRET not in json.dumps(row.result)  # target credentials never come back in evidence
    assert Relay("http://testserver", token, client=api).once() == "idle"


def test_relay_mode_verification_runs_in_the_relay_and_scope_is_checked_by_the_platform(relay_app, target, monkeypatch):
    ws, cred_id, token = relay_app
    monkeypatch.setattr(connections.settings(), "allow_private_targets", False)  # the hosted service itself cannot reach the target
    config = {"base_url": target, "manifest_path": "/manifest", "health_path": "/health", "scope": {"allowed_paths": ["/health"]},
              "execution": {"mode": "relay"}}
    with tenant_session(ws) as s:
        application = s.get(Application, f"{ws}-app")
        with pytest.raises(connections.OnboardingError) as exc:  # without a relay the private target is refused outright
            connections.create_connection(s, application, adapter_id="assureops-http-json-v1", actor="dev",
                                          config={k: v for k, v in config.items() if k != "execution"})
        assert exc.value.code == "destination_denied"
    with tenant_session(ws) as s:
        application = s.get(Application, f"{ws}-app")
        conn = connections.create_connection(s, application, adapter_id="assureops-http-json-v1", actor="dev", config=config)
        pending = connections.verify(s, application, conn, None)
        assert pending["status"] == "pending_relay"
        conn_id = conn.id
    assert Relay("http://testserver", token, client=TestClient(app)).once() == "done"
    with tenant_session(ws) as s:
        row = s.get(Connection, conn_id)
        assert row.verification["executed_by"] == "relay" and row.status in ("verified", "failed")
        assert {c["id"] for c in row.verification["checks"]} >= {"health", "manifest"}
        s.delete(row)
