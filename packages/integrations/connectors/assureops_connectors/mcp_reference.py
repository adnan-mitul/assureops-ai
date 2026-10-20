"""`assureops-mcp-reference`: the reference refund agent behind the AssureOps MCP gateway.

Manifest collection and connection checks are HTTP; test execution needs the
platform's approval service (synthetic approvals) and the MCP tool-side
ledger, so the worker installs the executor. It is the only adapter that runs
inside the worker process, and it only targets the bundled reference agent.
"""

from .base import Adapter, AdapterError, ConnectionSpec, TestContext, register
from .http_json import HttpJsonAdapter

_executor = None


def set_executor(fn):
    global _executor
    _executor = fn


class McpReferenceAdapter(Adapter):
    adapter_id = "assureops-mcp-reference"
    version = "0.3.0"
    evaluator_version = "reference-runner-1.0.0"

    def __init__(self):
        self._http = HttpJsonAdapter()

    def _as_http(self, spec: ConnectionSpec) -> ConnectionSpec:
        config = {"manifest_path": "/manifest", "health_path": "/health", "scope": {"allowed_paths": ["/chat", "/manifest"]},
                  "ownership": {"method": "manifest_application"}, **{k: v for k, v in spec.config.items() if k != "tools_url"}}
        return ConnectionSpec(adapter_id=spec.adapter_id, revision=spec.revision, config=config, credentials=spec.credentials,
                              allow_private=spec.allow_private)

    def collect_manifest(self, spec):
        return self._http.collect_manifest(self._as_http(spec))

    def validate_connection(self, spec, profile):
        result = self._http.validate_connection(self._as_http(spec), None)
        tools = spec.config.get("tools_url")
        result["checks"].append({"id": "tool_server", "status": "pass" if tools else "fail",
                                 "detail": f"tool-side ledger at {tools}" if tools else "tools_url is required"})
        if profile is not None:
            wrong = [t["id"] for t in profile["tests"] if t["template"] != "mcp_reference"]
            result["checks"].append({"id": "profile_scope", "status": "fail" if wrong else "pass",
                                     "detail": f"tests not runnable by this adapter: {wrong}" if wrong else f"all {len(profile['tests'])} tests use the reference runner"})
            result["capabilities"].update(tests_runnable=len(profile["tests"]) - len(wrong), tests_blocked=[{"test_id": w, "reason": "template"} for w in wrong])
        result["status"] = "failed" if any(c["status"] == "fail" for c in result["checks"]) else "verified"
        return result

    def run_allowed_test(self, spec, test, ctx: TestContext, trial: int = 0):
        if _executor is None:
            raise AdapterError("not_available", "the reference runner executes only inside the AssureOps worker")
        return _executor(spec, test, ctx, trial)

    def read_action_evidence(self, spec, query):
        raise AdapterError("unsupported", "reference agent evidence is read through the MCP tool server by the runner")

    def normalize_event(self, spec, raw, *, source_id, epoch):
        return {**raw, "source_id": source_id, "epoch": raw.get("epoch", epoch)}


register(McpReferenceAdapter())
