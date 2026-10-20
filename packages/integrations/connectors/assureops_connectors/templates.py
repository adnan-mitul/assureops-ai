"""Permitted test catalogue: parameterized templates that expand to scenarios.

Templates are application-agnostic. A profile (reviewed by people, or
proposed by phase C and then reviewed) supplies typed arguments: which actor,
endpoint, request body, response fields and markers. `scenario` accepts a
fully declared step list for anything the named templates do not cover.
Arguments are validated against each template's schema before a plan freezes.
"""

import copy
import re

import jsonschema

REQ = {"type": "object", "required": ["method", "path"], "properties": {
    "method": {"enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]}, "path": {"type": "string", "pattern": "^/"},
    "body": {}, "headers": {"type": "object"}}}
ACTOR = {"type": "string", "minLength": 1}
STATUSES = {"type": "array", "items": {"type": "integer"}, "minItems": 1}
STRINGS = {"type": "array", "items": {"type": "string"}}

TEMPLATES: dict[str, dict] = {
    "scenario": {
        "title": "Declared multi-step scenario",
        "description": "Ordered requests as named actors with captures and assertions.",
        "schema": {"type": "object", "required": ["steps", "assert"], "properties": {"steps": {"type": "array"}, "assert": {"type": "array"},
                                                                                    "vars": {"type": "object"}}},
    },
    "manifest_identity": {
        "title": "Running release matches the assessed manifest",
        "description": "Collects the live manifest and compares release identity and every component fingerprint.",
        "schema": {"type": "object", "properties": {}},
    },
    "auth_required": {
        "title": "Unauthenticated and forged identities are rejected",
        "schema": {"type": "object", "required": ["request"], "properties": {
            "request": REQ, "actors": {"type": "array", "items": {"enum": ["anonymous", "invalid"]}}, "deny_status": STATUSES}},
    },
    "role_forbidden": {
        "title": "An actor without the role cannot perform the operation",
        "schema": {"type": "object", "required": ["actor", "request"], "properties": {"actor": ACTOR, "request": REQ, "deny_status": STATUSES}},
    },
    "cross_origin_rejected": {
        "title": "Browser requests from an untrusted origin are rejected",
        "schema": {"type": "object", "required": ["actor", "request"], "properties": {
            "actor": ACTOR, "request": REQ, "origin": {"type": "string"}, "deny_status": STATUSES}},
    },
    "data_not_disclosed": {
        "title": "Protected data is not disclosed to this actor",
        "description": "Passes when the request is denied, or when it succeeds without any protected marker or reference.",
        "schema": {"type": "object", "required": ["actor", "request", "markers"], "properties": {
            "actor": ACTOR, "request": REQ, "markers": {**STRINGS, "minItems": 1}, "deny_status": STATUSES,
            "must_answer": {"type": "boolean"}, "inspect_path": {"type": "string"}}},
    },
    "authorized_access_works": {
        "title": "An authorized actor receives its own data",
        "description": "Positive control so a boundary test cannot pass merely because everything is blocked.",
        "schema": {"type": "object", "required": ["actor", "request", "expect_contains"], "properties": {
            "actor": ACTOR, "request": REQ, "expect_contains": {**STRINGS, "minItems": 1}, "inspect_path": {"type": "string"},
            "citations_path": {"type": "string"}, "expect_citations": STRINGS}},
    },
    "grounded_answer": {
        "title": "Answer contains the supported fact and cites its source",
        "schema": {"type": "object", "required": ["actor", "request", "reply_path", "expect_contains"], "properties": {
            "actor": ACTOR, "request": REQ, "reply_path": {"type": "string"}, "expect_contains": {**STRINGS, "minItems": 1},
            "citations_path": {"type": "string"}, "expect_citations": STRINGS}},
    },
    "abstains_when_unsupported": {
        "title": "Unanswerable question gets an abstention without invented citations",
        "schema": {"type": "object", "required": ["actor", "request", "reply_path", "abstention_patterns"], "properties": {
            "actor": ACTOR, "request": REQ, "reply_path": {"type": "string"}, "abstention_patterns": {**STRINGS, "minItems": 1},
            "citations_path": {"type": "string"}}},
    },
    "instruction_not_followed": {
        "title": "Instructions inside untrusted content are not followed",
        "description": "Sends a request that surfaces seeded untrusted content; passes when no canary/forbidden output appears.",
        "schema": {"type": "object", "required": ["actor", "request", "canaries"], "properties": {
            "actor": ACTOR, "request": REQ, "canaries": {**STRINGS, "minItems": 1}, "inspect_path": {"type": "string"},
            "must_answer": {"type": "boolean"}, "forbidden_actions_path": {"type": "string"}}},
    },
    "single_effect_under_concurrency": {
        "title": "Concurrent duplicate submissions take effect once",
        "schema": {"type": "object", "required": ["actor", "request", "ledger", "match"], "properties": {
            "actor": ACTOR, "request": REQ, "concurrency": {"type": "integer", "minimum": 2, "maximum": 8},
            "setup": {"type": "array"}, "ledger": {"type": "object", "required": ["actor", "request", "list_path"]},
            "match": {"type": "object"}, "success_status": STATUSES}},
    },
    "event_stream_integrity": {
        "title": "Event stream is ordered and carries the running release",
        "description": "Optionally sends a declared, harmless trigger request first so the stream contains an event from this run.",
        "schema": {"type": "object", "required": ["actor", "request", "list_path"], "properties": {
            "actor": ACTOR, "request": REQ, "list_path": {"type": "string"}, "sequence_field": {"type": "string"},
            "release_field": {"type": "string"}, "trigger": {"type": "object", "required": ["actor", "request"],
                                                              "properties": {"actor": ACTOR, "request": REQ}}}},
    },
}


class TemplateError(Exception):
    pass


def catalogue() -> list[dict]:
    return [{"id": tid, "title": t["title"], "description": t.get("description", ""), "schema": t["schema"]} for tid, t in TEMPLATES.items()]


def validate_args(template: str, args: dict) -> None:
    if template not in TEMPLATES:
        raise TemplateError(f"template {template!r} is not in the permitted catalogue")
    try:
        jsonschema.validate(args, TEMPLATES[template]["schema"])
    except jsonschema.ValidationError as exc:
        raise TemplateError(f"{template} arguments invalid at {'/'.join(map(str, exc.absolute_path)) or 'args'}: {exc.message}")


def _step(name: str, actor: str, request: dict, **extra) -> dict:
    step = {"name": name, "actor": actor, "method": request["method"], "path": request["path"]}
    if "body" in request:
        step["body"] = copy.deepcopy(request["body"])
    if request.get("headers"):
        step["headers"] = dict(request["headers"])
    step.update(extra)
    return step


def _inspect(args: dict, key: str = "inspect_path", default: str = "body") -> str:
    path = args.get(key) or default
    return path if path.startswith("body") else f"body.{path}"


def expand(template: str, args: dict) -> dict:
    """Template + arguments -> scenario (steps/assert). `manifest_identity` is evaluated by the adapter."""
    validate_args(template, args)
    a = copy.deepcopy(args)
    if template == "scenario":
        return {"steps": a["steps"], "assert": a["assert"], "vars": a.get("vars", {})}
    if template == "manifest_identity":
        return {"steps": [{"kind": "manifest", "name": "manifest"}], "assert": [], "manifest_identity": True}
    if template == "auth_required":
        deny = a.get("deny_status", [401, 403])
        actors = a.get("actors", ["anonymous", "invalid"])
        steps = [_step(f"as_{actor}", actor, a["request"]) for actor in actors]
        return {"steps": steps, "assert": [{"step": s["name"], "path": "status", "op": "in", "value": deny,
                                             "describe": f"{s['actor']} identity is rejected"} for s in steps]}
    if template == "role_forbidden":
        return {"steps": [_step("attempt", a["actor"], a["request"])],
                "assert": [{"step": "attempt", "path": "status", "op": "in", "value": a.get("deny_status", [401, 403, 404]),
                            "describe": "operation denied for this role"}]}
    if template == "cross_origin_rejected":
        req = {**a["request"], "headers": {**a["request"].get("headers", {}), "Origin": a.get("origin", "https://untrusted.example")}}
        return {"steps": [_step("attempt", a["actor"], req)],
                "assert": [{"step": "attempt", "path": "status", "op": "in", "value": a.get("deny_status", [401, 403]),
                            "describe": "untrusted origin rejected"}]}
    if template == "data_not_disclosed":
        path = _inspect(a)
        not_leaked = [{"step": "attempt", "path": path, "op": "contains_none", "value": a["markers"], "describe": "no protected marker in the response"}]
        if a.get("must_answer"):
            return {"steps": [_step("attempt", a["actor"], a["request"])],
                    "assert": [{"step": "attempt", "path": "status", "op": "eq", "value": 200, "describe": "request answered"}, *not_leaked]}
        return {"steps": [_step("attempt", a["actor"], a["request"])],
                "assert": [{"any": [{"step": "attempt", "path": "status", "op": "in", "value": a.get("deny_status", [401, 403, 404])},
                                    {"step": "attempt", "path": path, "op": "contains_none", "value": a["markers"]}],
                            "describe": "denied, or answered without protected data"},
                           {"step": "attempt", "path": "status", "op": "lt", "value": 500, "describe": "no server error"}]}
    if template == "authorized_access_works":
        path = _inspect(a)
        checks = [{"step": "attempt", "path": "status", "op": "eq", "value": 200, "describe": "authorized request succeeds"}]
        checks += [{"step": "attempt", "path": path, "op": "contains", "value": v, "describe": f"response includes {v}"} for v in a["expect_contains"]]
        if a.get("citations_path") and a.get("expect_citations") is not None:
            checks.append({"step": "attempt", "path": _inspect(a, "citations_path"), "op": "eq", "value": a["expect_citations"],
                           "describe": "cites exactly the authorized source"})
        return {"steps": [_step("attempt", a["actor"], a["request"])], "assert": checks}
    if template == "grounded_answer":
        reply = _inspect(a, "reply_path")
        checks = [{"step": "ask", "path": "status", "op": "eq", "value": 200, "describe": "question answered"}]
        checks += [{"step": "ask", "path": reply, "op": "contains", "value": v, "describe": f"answer states {v}"} for v in a["expect_contains"]]
        if a.get("citations_path"):
            cite = _inspect(a, "citations_path")
            checks.append({"step": "ask", "path": cite, "op": "eq", "value": a["expect_citations"], "describe": "cites the supporting source"}
                          if a.get("expect_citations") is not None else
                          {"step": "ask", "path": cite, "op": "len_gte", "value": 1, "describe": "cites at least one source"})
        return {"steps": [_step("ask", a["actor"], a["request"])], "assert": checks}
    if template == "abstains_when_unsupported":
        pattern = "|".join(re.escape(p).replace("'", "['’]") for p in a["abstention_patterns"])
        checks = [{"step": "ask", "path": "status", "op": "eq", "value": 200, "describe": "question answered"},
                  {"step": "ask", "path": _inspect(a, "reply_path"), "op": "matches", "value": f"({pattern})", "describe": "answer abstains"}]
        if a.get("citations_path"):
            checks.append({"step": "ask", "path": _inspect(a, "citations_path"), "op": "absent", "describe": "no invented citation"})
        return {"steps": [_step("ask", a["actor"], a["request"])], "assert": checks}
    if template == "instruction_not_followed":
        path = _inspect(a)
        checks = [{"step": "ask", "path": path, "op": "contains_none", "value": a["canaries"], "describe": "seeded canary not disclosed"}]
        if a.get("must_answer", True):
            checks.insert(0, {"step": "ask", "path": "status", "op": "eq", "value": 200, "describe": "request answered"})
        if a.get("forbidden_actions_path"):
            checks.append({"step": "ask", "path": _inspect(a, "forbidden_actions_path"), "op": "absent", "describe": "no action triggered"})
        return {"steps": [_step("ask", a["actor"], a["request"])], "assert": checks}
    if template == "single_effect_under_concurrency":
        steps = list(a.get("setup", []))
        steps.append(_step("submit", a["actor"], a["request"], parallel=a.get("concurrency", 2)))
        ledger = a["ledger"]
        steps.append(_step("ledger", ledger["actor"], ledger["request"]))
        list_path = _inspect({"p": ledger["list_path"]}, "p")
        checks = [{"step": "submit", "path": "*.status", "op": "subset_of", "value": a.get("success_status", [200, 201, 409]),
                   "describe": "every submission answered without server error"},
                  {"step": "ledger", "path": list_path, "op": "count_where", "where": a["match"], "value": 1,
                   "describe": "exactly one effect recorded"}]
        return {"steps": steps, "assert": checks}
    if template == "event_stream_integrity":
        list_path = _inspect({"p": a["list_path"]}, "p")
        seq, rel = a.get("sequence_field", "sequence"), a.get("release_field", "release")
        trigger = [_step("trigger", a["trigger"]["actor"], a["trigger"]["request"])] if a.get("trigger") else []
        return {"steps": [*trigger, _step("events", a["actor"], a["request"])],
                "assert": [{"step": "events", "path": "status", "op": "eq", "value": 200, "describe": "event stream readable"},
                           {"step": "events", "path": f"{list_path}.*.{seq}", "op": "strictly_increasing", "describe": "sequence ordered without duplicates"},
                           {"step": "events", "path": f"{list_path}.-1.{rel}", "op": "eq", "value": "{{release}}",
                            "describe": "latest event carries the running release"}]}
    raise TemplateError(template)


def request_paths(template: str, args: dict) -> list[tuple[str, str]]:
    """(method, path) pairs a test would send, for scope verification before execution."""
    scenario = expand(template, args)
    out = []
    for step in scenario["steps"]:
        if step.get("kind") == "manifest":
            continue
        out.append((step["method"], step["path"]))
    return out


def actors_used(template: str, args: dict) -> set[str]:
    scenario = expand(template, args)
    return {s.get("actor", "anonymous") for s in scenario["steps"] if s.get("kind") != "manifest"}
