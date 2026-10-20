"""A write whose response times out is reconciled from the target's action records and never re-sent."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assureops_connectors.base import ConnectionSpec, TestContext
from assureops_connectors.http_json import HttpJsonAdapter
from assureops_connectors.scenario import AmbiguousOutcome

LEDGER: list[dict] = []
WRITES: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        WRITES.append(body["action_id"])
        LEDGER.append({"action_id": body["action_id"], "amount": 1})  # committed before the slow answer
        time.sleep(2.5)
        try:
            self._send(200, {"ok": True})
        except OSError:
            pass

    def do_GET(self):
        self._send(200, {"refunds": LEDGER})


@pytest.fixture(scope="module")
def target():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_timed_out_write_is_reconciled_not_resent(target):
    spec = ConnectionSpec(adapter_id="assureops-http-json-v1", revision=1, allow_private=True, credentials={"customer": "t"}, config={
        "base_url": target, "manifest_path": "/manifest", "request_timeout_seconds": 1,
        "scope": {"allowed_paths": ["/refunds", "/actions"]},
        "action_evidence": {"actor": "customer", "method": "GET", "path": "/actions", "list_path": "refunds"}})
    test = {"id": "W1", "control": "C08", "severity": "high", "trials": 1, "name": "write", "expected": "x", "template": "scenario",
            "args": {"steps": [{"name": "w", "actor": "customer", "method": "POST", "path": "/refunds", "body": {"action_id": "{{run}}-w"}}],
                     "assert": [{"step": "w", "path": "status", "op": "eq", "value": 200}]}}
    ctx = TestContext(step_id="s", release_version="R1", frozen_manifest={}, run_tokens=["ao-aaaaaaaaaaaa"])
    with pytest.raises(AmbiguousOutcome) as exc:
        HttpJsonAdapter().run_allowed_test(spec, test, ctx, 0)
    rec = exc.value.record["ambiguous_write"]
    assert rec["action_id"] == "ao-aaaaaaaaaaaa-w" and rec["reconciliation"]["status"] == "found"
    assert WRITES.count("ao-aaaaaaaaaaaa-w") == 1  # reconciled from the system of record, never sent again
