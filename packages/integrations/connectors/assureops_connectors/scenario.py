"""Declarative scenario engine.

A test is data: ordered HTTP steps performed as named actors, values captured
from responses, then assertions over the recorded results. There is no code
execution from profiles or model output; only the operators in
`assureops_domain.matchers` exist.

Interpolation: `{{name}}` in any string, where name is `run` (unique per
trial), `release` (the frozen assessed release), a declared `vars` entry or a
capture. A string that is exactly `{{name}}` keeps the captured value's type.
"""

import concurrent.futures
import re
import secrets

from assureops_domain import matchers

from .http_client import TargetClient, TargetError, evidence_view

VAR = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
MAX_STEPS = 25
MAX_PARALLEL = 8
MAX_REPEAT = 10


class ScenarioError(Exception):
    """The scenario definition is invalid (a profile problem, not an application defect)."""


class PreconditionFailed(TargetError):
    """A setup step did not produce what later steps need; the check could not be completed."""

    def __init__(self, message: str, record: dict):
        super().__init__(message)
        self.record = record


def interpolate(value, ctx: dict):
    if isinstance(value, str):
        whole = VAR.fullmatch(value.strip())
        if whole:
            return _var(whole.group(1), ctx)
        return VAR.sub(lambda m: str(_var(m.group(1), ctx)), value)
    if isinstance(value, list):
        return [interpolate(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: interpolate(v, ctx) for k, v in value.items()}
    return value


def _var(name: str, ctx: dict):
    head, _, rest = name.partition(".")
    if head not in ctx:
        raise ScenarioError(f"undefined variable {{{{{name}}}}}")
    value = ctx[head]
    if rest:
        value = matchers.lookup(value, rest)
        if value is matchers.MISSING:
            raise ScenarioError(f"variable path {{{{{name}}}}} not found")
    return value


def _check_assertion(a: dict, results: dict, ctx: dict) -> dict:
    if "any" in a:
        parts = [_check_assertion(x, results, ctx) for x in a["any"]]
        return {"any": parts, "passed": any(p["passed"] for p in parts), "describe": a.get("describe")}
    step = a.get("step")
    if step not in results:
        return {"step": step, "passed": False, "reason": "step did not run", "describe": a.get("describe")}
    actual = matchers.lookup(results[step], a.get("path", "status"))
    expected = interpolate(a.get("value"), ctx)
    where = interpolate(a.get("where"), ctx) if a.get("where") else None
    passed = matchers.compare(actual, a["op"], expected, where)
    shown = actual if actual is not matchers.MISSING else "<missing>"
    if isinstance(shown, (dict, list)) and len(str(shown)) > 400:
        shown = str(shown)[:400] + "..."
    return {"step": step, "path": a.get("path", "status"), "op": a["op"], "expected": expected, "where": where,
            "actual": shown, "passed": passed, "describe": a.get("describe")}


def validate(scenario: dict, actor_names: set[str]) -> None:
    steps = scenario.get("steps", [])
    if not steps or len(steps) > MAX_STEPS:
        raise ScenarioError(f"a scenario needs 1..{MAX_STEPS} steps")
    names = set()
    for step in steps:
        if step.get("kind") == "manifest":
            names.add(step.get("name", "manifest"))
            continue
        for key in ("name", "method", "path"):
            if key not in step:
                raise ScenarioError(f"step is missing {key}")
        if step["name"] in names:
            raise ScenarioError(f"duplicate step name {step['name']}")
        names.add(step["name"])
        if step.get("actor", "anonymous") not in actor_names:
            raise ScenarioError(f"step {step['name']} uses undeclared actor {step.get('actor')}")
        if not 1 <= int(step.get("parallel", 1)) <= MAX_PARALLEL or not 1 <= int(step.get("repeat", 1)) <= MAX_REPEAT:
            raise ScenarioError(f"step {step['name']} parallel/repeat out of bounds")
    if not scenario.get("assert"):
        raise ScenarioError("a scenario needs at least one assertion")
    for a in scenario["assert"]:
        for item in a.get("any", [a]):
            if item.get("step") not in names:
                raise ScenarioError(f"assertion references unknown step {item.get('step')}")
            if item.get("op") not in matchers.OPERATORS:
                raise ScenarioError(f"unsupported operator {item.get('op')}")


def run(scenario: dict, client: TargetClient, *, release: str, manifest_fetch=None, base_vars: dict | None = None) -> tuple[bool, dict]:
    """Execute one trial. Returns (passed, evidence record). Raises TargetError for transport problems."""
    validate(scenario, client.actors.names())
    ctx = {"run": "ao-" + secrets.token_hex(5), "release": release, **(base_vars or {}), **(scenario.get("vars") or {})}
    results, transcript = {}, []
    for step in scenario["steps"]:
        if step.get("kind") == "manifest":
            name = step.get("name", "manifest")
            results[name] = {"status": 200, "body": manifest_fetch()}
            transcript.append({"step": name, "kind": "manifest", "response": evidence_view(results[name])})
            continue
        method, path = step["method"], interpolate(step["path"], ctx)
        body = interpolate(step.get("body"), ctx) if "body" in step else None
        headers = interpolate(step.get("headers"), ctx) if step.get("headers") else None
        actor = step.get("actor", "anonymous")
        parallel, repeat = int(step.get("parallel", 1)), int(step.get("repeat", 1))

        def send():
            return client.request(method, path, actor=actor, body=body, headers=headers)

        if parallel > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = [pool.submit(send) for _ in range(parallel)]
                outcome = [f.result() for f in futures]
        elif repeat > 1:
            outcome = [send() for _ in range(repeat)]
        else:
            outcome = send()
        results[step["name"]] = outcome
        transcript.append({"step": step["name"], "actor": actor, "request": {"method": method, "path": path, "body": body,
                           "extra_headers": sorted((headers or {}).keys()), "parallel": parallel, "repeat": repeat},
                           "response": [evidence_view(o) for o in outcome] if isinstance(outcome, list) else evidence_view(outcome)})
        for var, cpath in (step.get("capture") or {}).items():
            source = outcome[0] if isinstance(outcome, list) else outcome
            value = matchers.lookup(source, cpath)
            if value is matchers.MISSING:
                # The application did not return what the next steps need: unverified, never a pass or a fail.
                raise PreconditionFailed(f"step {step['name']} returned no {cpath} to capture as {var}",
                                         {"run": ctx["run"], "transcript": transcript, "assertions": []})
            ctx[var] = value
    checks = [_check_assertion(a, results, ctx) for a in scenario["assert"]]
    passed = all(c["passed"] for c in checks)
    return passed, {"run": ctx["run"], "transcript": transcript, "assertions": checks}


__all__ = ["run", "validate", "interpolate", "ScenarioError", "TargetError", "PreconditionFailed"]
