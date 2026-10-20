"""Generic connector engine: egress policy, scope, redirects, size limits, credential hygiene, precondition handling."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assureops_connectors import scenario, templates
from assureops_connectors.egress import EgressDenied, check_path, check_target
from assureops_connectors.http_client import Actors, TargetClient, TargetError
from assureops_worker import isolation

SECRET = "test-bearer-value-123456"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, status, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        if self.path == "/redirect":
            return self._send(302, {"moved": True}, {"Location": "http://169.254.169.254/latest/meta-data/"})
        if self.path == "/huge":
            return self._send(200, b"x" * 700_000)
        if self.path == "/me":
            return self._send(200 if auth == f"Bearer {SECRET}" else 401, {"echo_auth_seen": bool(auth)})
        if self.path == "/empty":
            return self._send(200, {"no_id_here": True})
        return self._send(404, {"error": "nope"})

    do_POST = do_GET


@pytest.fixture(scope="module")
def target():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def client(origin, paths=("/me", "/redirect", "/huge", "/empty")):
    return TargetClient(origin, {"allowed_paths": list(paths), "allowed_methods": ["GET", "POST"]}, Actors(None, {"user": SECRET}))


def test_metadata_and_private_targets_are_refused():
    with pytest.raises(EgressDenied):
        check_target("http://169.254.169.254", allow_private=True)
    with pytest.raises(EgressDenied):
        check_target("http://127.0.0.1:8811", allow_private=False)
    with pytest.raises(EgressDenied):
        check_target("http://user:pw@example.com", allow_private=True)
    with pytest.raises(EgressDenied):
        check_target("http://example.com/some/path", allow_private=True)
    assert check_target("http://127.0.0.1:8811", allow_private=True)["address_class"] == "private"


@pytest.mark.parametrize("path", ["/admin", "/me/../admin", "//evil.example/x", "http://evil.example/me", "/me\\..\\admin"])
def test_out_of_scope_or_traversal_paths_are_refused(path):
    with pytest.raises(EgressDenied):
        check_path(path, ["/me"], "GET", ["GET"])


def test_method_outside_scope_is_refused():
    with pytest.raises(EgressDenied):
        check_path("/me", ["/me"], "DELETE", ["GET", "POST"])


def test_redirect_is_recorded_not_followed(target):
    res = client(target).request("GET", "/redirect", actor="user")
    assert res["status"] == 302 and res["redirect_not_followed"].startswith("http://169.254.169.254")


def test_oversized_response_is_a_target_error_not_a_result(target):
    with pytest.raises(TargetError):
        client(target).request("GET", "/huge", actor="user")


def test_credentials_never_reach_evidence(target):
    sc = {"steps": [{"name": "who", "actor": "user", "method": "GET", "path": "/me"},
                    {"name": "forged", "actor": "invalid", "method": "GET", "path": "/me"}],
          "assert": [{"step": "who", "path": "status", "op": "eq", "value": 200}, {"step": "forged", "path": "status", "op": "eq", "value": 401}]}
    passed, record = scenario.run(sc, client(target), release="R1")
    assert passed
    assert SECRET not in json.dumps(record)


def test_missing_capture_is_unverified_not_failed(target):
    sc = {"steps": [{"name": "setup", "actor": "user", "method": "GET", "path": "/empty", "capture": {"approval_id": "body.id"}},
                    {"name": "use", "actor": "user", "method": "GET", "path": "/me"}],
          "assert": [{"step": "use", "path": "status", "op": "eq", "value": 200}]}
    with pytest.raises(scenario.PreconditionFailed):
        scenario.run(sc, client(target), release="R1")


def test_undeclared_actor_and_unknown_template_are_rejected():
    with pytest.raises(scenario.ScenarioError):
        scenario.validate({"steps": [{"name": "x", "actor": "root", "method": "GET", "path": "/me"}],
                           "assert": [{"step": "x", "op": "eq", "value": 200}]}, {"user", "anonymous", "invalid"})
    with pytest.raises(templates.TemplateError):
        templates.validate_args("run_shell", {})
    with pytest.raises(templates.TemplateError):
        templates.validate_args("data_not_disclosed", {"actor": "user"})


def test_runner_environment_carries_no_platform_secrets(monkeypatch):
    for key in ("DATABASE_URL", "OWNER_DATABASE_URL", "ASSUREOPS_SECRET_KEY", "GROQ_API_KEY", "S3_SECRET_KEY", "REDIS_URL", "RUN_TOKEN_KEY"):
        monkeypatch.setenv(key, "must-not-leak")
    env = isolation.scrubbed_env()
    assert "must-not-leak" not in json.dumps(env)
    assert set(env) <= set(isolation.SAFE_ENV_KEYS) | {"PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "NO_PROXY"}


def test_sandbox_runs_one_capsule_and_scope_violation_is_an_error(target):
    test = {"id": "X1", "control": "C01", "severity": "high", "trials": 1, "name": "probe", "expected": "denied", "template": "role_forbidden",
            "args": {"actor": "user", "request": {"method": "GET", "path": "/outside-scope"}}, "digest": "d"}
    capsule = {"adapter_id": "assureops-http-json-v1", "connection_revision": 1, "allow_private": True, "step_id": "s1", "release_version": "R1",
               "frozen_manifest": {}, "manifest_hash": "", "run_tokens": ["ao-000000000000"], "test": test,
               "config": {"base_url": target, "manifest_path": "/manifest", "scope": {"allowed_paths": ["/me"]}}, "credentials": {"user": SECRET}}
    out = isolation.run_capsule(capsule, timeout=30)
    assert out["status"] == "error" and "outside the authorized scope" in out["error"]
    assert SECRET not in json.dumps(out)
