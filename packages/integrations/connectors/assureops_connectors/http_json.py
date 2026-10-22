"""`assureops-http-json-v1`: generic adapter for HTTP/JSON applications.

Works for any application that exposes a JSON manifest and JSON endpoints:
chat assistants, retrieval services, agents with action APIs. The profile's
tests are permitted templates with typed arguments; this adapter only sends
requests inside the connection's authorized scope and records what happened.

`assureops-http-demo-v1` (the adapter id declared by the supplied demo
applications) is an alias of this adapter.
"""

from assureops_domain import matchers

from . import scenario as scenario_engine
from . import templates
from .base import Adapter, AdapterError, ConnectionSpec, TestContext, check_manifest, register
from .egress import EgressDenied, check_target
from .http_client import Actors, TargetClient, TargetError, evidence_view

DEFAULT_SCOPE = {"allowed_paths": [], "allowed_methods": ["GET", "POST"], "max_requests_per_test": 60}
CONFIG_KEYS = {"base_url", "environment", "manifest_path", "health_path", "auth", "actors", "scope", "test_marker_header",
               "ownership", "events", "credential_probe", "action_evidence", "actor_identities", "lab",
               "host_header", "runner_network", "request_timeout_seconds", "execution"}


def _check(cid: str, status: str, detail: str) -> dict:
    return {"id": cid, "status": status, "detail": detail}


class HttpJsonAdapter(Adapter):
    adapter_id = "assureops-http-json-v1"
    version = "1.0.0"
    evaluator_version = "scenario-engine-1.0.0"

    # ---------------- helpers ----------------

    def client(self, spec: ConnectionSpec, marker: str | None = None) -> TargetClient:
        target = check_target(spec.base_url, allow_private=spec.allow_private)
        scope = {**DEFAULT_SCOPE, **(spec.config.get("scope") or {})}
        return TargetClient(target["origin"], scope, Actors(spec.config.get("auth"), spec.credentials),
                            marker_header=spec.config.get("test_marker_header", "X-AssureOps-Test"), marker_value=marker,
                            timeout=float(spec.config.get("request_timeout_seconds", 15)), host_header=spec.config.get("host_header"))

    @staticmethod
    def validate_config(config: dict) -> list[str]:
        problems = [f"unknown setting {k}" for k in sorted(set(config) - CONFIG_KEYS)]
        for key in ("base_url", "manifest_path"):
            if not config.get(key):
                problems.append(f"{key} is required")
        scope = config.get("scope") or {}
        if not scope.get("allowed_paths"):
            problems.append("scope.allowed_paths must list the paths tests may use")
        return problems

    # ---------------- contract ----------------

    def collect_manifest(self, spec: ConnectionSpec) -> dict:
        client = self.client(spec)
        try:
            result = client.request("GET", spec.config.get("manifest_path", "/manifest"), enforce_scope=False)
        except (TargetError, EgressDenied) as exc:
            raise AdapterError("target_unreachable", f"could not collect the manifest: {exc}")
        finally:
            client.close()
        if result["status"] != 200:
            raise AdapterError("invalid_manifest", f"manifest endpoint answered HTTP {result['status']}")
        manifest = result["body"]
        problems = check_manifest(manifest)
        if problems:
            raise AdapterError("invalid_manifest", "manifest rejected: " + "; ".join(problems))
        gaps = list((manifest.get("collection") or {}).get("gaps", []))
        gaps += [f"declared unknown: {u}" for u in (manifest.get("collection") or {}).get("unknowns", [])]
        expected = (spec.config.get("ownership") or {}).get("expected_application")
        if expected and manifest.get("application") != expected:
            raise AdapterError("identity_mismatch", f"target reports application {manifest.get('application')!r}, connection expects {expected!r}")
        return {"manifest": manifest, "gaps": gaps}

    def validate_connection(self, spec: ConnectionSpec, profile: dict | None) -> dict:
        checks, gaps = [], []
        problems = self.validate_config(spec.config)
        if problems:
            checks.append(_check("configuration", "fail", "; ".join(problems)))
            return self._summary(checks, gaps, {})
        try:
            target = check_target(spec.base_url, allow_private=spec.allow_private)
            checks.append(_check("destination", "pass", f"{target['origin']} ({target['address_class']} address); redirects are never followed"))
            if target["address_class"] == "private":
                gaps.append("target is on a private/loopback address: reachable only from this deployment's authorized network")
        except EgressDenied as exc:
            checks.append(_check("destination", "fail", str(exc)))
            return self._summary(checks, gaps, {})

        client = self.client(spec)
        capabilities = {"health": False, "manifest": False, "events": False, "action_evidence": bool(spec.config.get("action_evidence"))}
        try:
            try:
                health = client.request("GET", spec.config.get("health_path", "/health"), enforce_scope=False)
                capabilities["health"] = health["status"] == 200
                checks.append(_check("health", "pass" if capabilities["health"] else "fail", f"HTTP {health['status']}"))
            except TargetError as exc:
                checks.append(_check("health", "fail", str(exc)))
                return self._summary(checks, gaps, capabilities)

            try:
                collected = self.collect_manifest(spec)
                capabilities["manifest"] = True
                manifest = collected["manifest"]
                gaps += collected["gaps"]
                checks.append(_check("manifest", "pass", f"release {manifest['release']}, {len(manifest['components'])} components"))
            except AdapterError as exc:
                checks.append(_check("manifest", "fail", exc.detail))
                manifest = None

            ownership = spec.config.get("ownership") or {}
            method = ownership.get("method", "none")
            if method == "well_known_token":
                try:
                    res = client.request("GET", ownership.get("path", "/.well-known/assureops-verification.txt"), enforce_scope=False)
                    ok = res["status"] == 200 and isinstance(res["body"], (str, dict)) and ownership.get("token", "\0") in str(res["body"])
                    checks.append(_check("ownership", "pass" if ok else "fail",
                                         "verification token served by the target" if ok else "verification token not found at the target"))
                except TargetError as exc:
                    checks.append(_check("ownership", "fail", str(exc)))
            elif method == "manifest_application" and manifest:
                checks.append(_check("ownership", "gap", f"manifest declares application {manifest['application']!r}; this is an assertion, not proof of control"))
                gaps.append("ownership asserted by manifest only; publish a verification token for strong proof before hosted use")
            else:
                checks.append(_check("ownership", "fail", "no ownership verification configured"))

            actors = spec.config.get("actors") or {}
            missing = sorted(a for a in actors if a not in spec.credentials)
            if missing:
                checks.append(_check("credentials", "fail", f"no active credential for actors: {', '.join(missing)}"))
            probe = spec.config.get("credential_probe")
            if probe and not missing:
                rejected = []
                for actor in actors:
                    try:
                        res = client.request(probe.get("method", "GET"), probe["path"], actor=actor, enforce_scope=False)
                        if res["status"] == 401:
                            rejected.append(actor)
                    except TargetError as exc:
                        rejected.append(f"{actor} ({exc})")
                checks.append(_check("credentials", "fail" if rejected else "pass",
                                     f"rejected by target: {', '.join(rejected)}" if rejected else f"{len(actors)} actor credentials accepted"))
            elif not actors:
                checks.append(_check("credentials", "pass", "no actor credentials configured for this connection"))
            elif not missing:
                checks.append(_check("credentials", "gap", "credentials stored but not probed (no credential_probe configured)"))
                gaps.append("actor credentials were not probed before testing")

            events = spec.config.get("events")
            if events:
                try:
                    res = client.request("GET", events["path"], actor=events.get("actor"), enforce_scope=False)
                    listed = matchers.lookup(res["body"], events.get("list_path", "events")) if res["status"] == 200 else matchers.MISSING
                    capabilities["events"] = isinstance(listed, list)
                    checks.append(_check("events", "pass" if capabilities["events"] else "fail",
                                         f"{len(listed)} events readable" if capabilities["events"] else f"HTTP {res['status']}"))
                    if events.get("format") != "assureops-v1":
                        gaps.append(f"runtime events are {events.get('format', 'unsigned')} pull records: they need the AssureOps bridge "
                                    "(source credential, epoch, sequence) before platform ingestion")
                except (TargetError, EgressDenied) as exc:
                    checks.append(_check("events", "fail", str(exc)))
            else:
                gaps.append("no runtime event source: monitoring coverage is not_connected")
        finally:
            client.close()

        if profile is not None:
            blocked = self.profile_compatibility(spec, profile)
            capabilities["tests_runnable"] = len(profile["tests"]) - len(blocked)
            capabilities["tests_blocked"] = blocked
            checks.append(_check("profile_scope", "fail" if blocked else "pass",
                                 f"{len(blocked)} tests cannot run within this connection: " + "; ".join(f"{b['test_id']}: {b['reason']}" for b in blocked)
                                 if blocked else f"all {len(profile['tests'])} profile tests are inside the authorized scope"))
        return self._summary(checks, gaps, capabilities)

    def profile_compatibility(self, spec: ConnectionSpec, profile: dict) -> list[dict]:
        scope = {**DEFAULT_SCOPE, **(spec.config.get("scope") or {})}
        names = set(spec.config.get("actors") or {}) | {"anonymous", "invalid"}
        blocked = []
        for test in profile["tests"]:
            try:
                if test["template"] == "mcp_reference":
                    raise templates.TemplateError("MCP reference tests need the assureops-mcp-reference adapter")
                for method, path in templates.request_paths(test["template"], test["args"]):
                    if "{{" not in path:
                        from .egress import check_path
                        check_path(path, scope["allowed_paths"], method, scope["allowed_methods"])
                unknown = templates.actors_used(test["template"], test["args"]) - names
                if unknown:
                    raise templates.TemplateError(f"undeclared actors {sorted(unknown)}")
                scenario_engine.validate(templates.expand(test["template"], test["args"]), names) if test["template"] != "manifest_identity" else None
            except (templates.TemplateError, EgressDenied, scenario_engine.ScenarioError) as exc:
                blocked.append({"test_id": test["id"], "reason": str(exc)})
        return blocked

    @staticmethod
    def _summary(checks: list[dict], gaps: list[str], capabilities: dict) -> dict:
        failed = [c for c in checks if c["status"] == "fail"]
        return {"status": "failed" if failed else "verified", "checks": checks, "gaps": sorted(set(gaps)), "capabilities": capabilities}

    def run_allowed_test(self, spec: ConnectionSpec, test: dict, ctx: TestContext, trial: int = 0) -> tuple[bool, dict]:
        expanded = templates.expand(test["template"], test["args"])
        client = self.client(spec, marker=ctx.step_id)
        try:
            if expanded.get("manifest_identity"):
                live = self.collect_manifest(spec)["manifest"]
                expected = ctx.frozen_manifest
                mismatched = sorted(c for c in set(live["components"]) | set(expected["components"])
                                    if live["components"].get(c) != expected["components"].get(c))
                same = live["release"] == expected["release"] and not mismatched
                return same, {"template": test["template"], "live_release": live["release"], "assessed_release": expected["release"],
                              "mismatched_components": mismatched}
            run_token = ctx.run_tokens[trial] if trial < len(ctx.run_tokens) else None
            base_vars = {"run": run_token} if run_token else {}
            reconcile = None
            if spec.config.get("action_evidence"):
                def reconcile(where: dict) -> dict:  # read the system of record; the ambiguous write is never re-sent
                    try:
                        return self.read_action_evidence(spec, {"where": where})
                    except (TargetError, EgressDenied, AdapterError) as exc:
                        return {"status": "unavailable", "error": str(exc), "matches": []}
            passed, record = scenario_engine.run(expanded, client, release=ctx.release_version,
                                                 manifest_fetch=lambda: self.collect_manifest(spec)["manifest"], base_vars=base_vars,
                                                 reconcile=reconcile)
            record.update(template=test["template"], requests_made=client.requests_made)
            return passed, record
        finally:
            client.close()

    def read_action_evidence(self, spec: ConnectionSpec, query: dict) -> dict:
        """Tool-side / system-of-record lookup used for reconciliation; never re-executes the action."""
        source = {**(spec.config.get("action_evidence") or {}), **query}
        if not source.get("path"):
            raise AdapterError("unsupported", "this connection declares no action evidence source")
        client = self.client(spec)
        try:
            res = client.request(source.get("method", "GET"), source["path"], actor=source.get("actor"))
        finally:
            client.close()
        rows = matchers.lookup(res["body"], source.get("list_path", "")) if res["status"] == 200 else matchers.MISSING
        if not isinstance(rows, list):
            return {"status": "unavailable", "http_status": res["status"], "matches": []}
        where = source.get("where") or {}
        found = [r for r in rows if all(matchers.lookup(r, k) == v for k, v in where.items())]
        return {"status": "found" if found else "not_found", "matches": found[:20], "response": evidence_view(res)}

    def normalize_event(self, spec: ConnectionSpec, raw: dict, *, source_id: str, epoch: str) -> dict:
        fmt = (spec.config.get("events") or {}).get("format", "assureops-v1")
        if fmt == "assureops-v1":
            return {**raw, "source_id": source_id, "epoch": raw.get("epoch", epoch)}
        if fmt == "local-lab-v1":
            payload = dict(raw.get("data") or {})
            payload.update(actor=raw.get("actor"), tenant=raw.get("tenant"), upstream_event_id=raw.get("event_id"))
            return {"event_id": f"{source_id}:{epoch}:{raw['event_id']}", "source_id": source_id, "epoch": epoch, "seq": int(raw["sequence"]),
                    "release": raw.get("release", "unknown"), "event_type": raw["type"], "observed_at": float(raw["observed_at"]),
                    "payload": payload}
        raise AdapterError("unsupported_event_format", f"event format {fmt!r} is not supported")


_ADAPTER = HttpJsonAdapter()
register(_ADAPTER, "assureops-http-demo-v1")
