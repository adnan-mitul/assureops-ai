"""Versioned control catalog, per-application profiles and adapter coverage contracts.

The control catalog (C01-C10) is shared. Each application has its own reviewed
profile revision that selects which controls it tests and how; controls
without tests stay visible as unassessed instead of being counted as passing.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

COMPONENT_LABELS = {
    "prompt": "Prompt update", "model": "Model update", "policy": "Policy change", "tool": "Tool schema change",
    "tools": "Tool registry change", "config": "Config change", "corpus": "Corpus update", "code": "Code update",
    "protocol": "Protocol change",
}

PROFILE_SCHEMA = {
    "type": "object",
    "required": ["profile_id", "version", "catalog", "adapter", "requirements", "gate_policy", "evidence_freshness_days", "tests"],
    "properties": {
        "profile_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9.-]{1,60}$"},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "catalog": {"type": "string"},
        "adapter": {"type": "string"},
        "scope": {"type": "object"},
        "requirements": {"type": "object", "required": ["self_approval_allowed"]},
        "gate_policy": {"type": "object", "required": ["version", "blocking_severities"]},
        "evidence_freshness_days": {"type": "integer", "minimum": 1, "maximum": 365},
        "coverage": {"type": "object"},
        "coverage_contract": {"type": "string"},
        # Reviewed reasons for catalog controls this profile does not test (activated by a second person with the profile).
        "applicability": {
            "type": "object",
            "propertyNames": {"pattern": "^C[0-9]{2}$"},
            "additionalProperties": {
                "type": "object", "required": ["status", "reason"], "additionalProperties": False,
                "properties": {"status": {"enum": ["not_applicable", "not_assessed"]}, "reason": {"type": "string", "minLength": 20, "maxLength": 600}},
            },
        },
        "tests": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "control", "severity", "trials", "name", "expected", "template", "args"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{2,40}$"},
                    "control": {"type": "string"},
                    "severity": {"enum": list(SEVERITY_RANK)},
                    "trials": {"type": "integer", "minimum": 1, "maximum": 10},
                    "name": {"type": "string", "minLength": 3},
                    "expected": {"type": "string", "minLength": 3},
                    "template": {"type": "string"},
                    "args": {"type": "object"},
                    "mandatory": {"type": "boolean"},
                    "requires_review": {"type": "boolean"},
                },
            },
        },
    },
}


class ProfileError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache
def control_catalog() -> dict:
    return json.loads(settings().catalog_path.read_text(encoding="utf-8"))


def catalog_id() -> str:
    c = control_catalog()
    return f"{c['catalog_id']}-v{c['version'].split('.')[0]}"


def validate(raw: dict) -> None:
    """Structural and referential checks; raises ProfileError with the first problem."""
    try:
        jsonschema.validate(raw, PROFILE_SCHEMA)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "profile"
        raise ProfileError("invalid_profile", f"{where}: {exc.message}")
    if raw["catalog"] != catalog_id():
        raise ProfileError("invalid_profile", f"profile targets catalog {raw['catalog']}, this platform serves {catalog_id()}")
    controls = control_catalog()["controls"]
    seen = set()
    for test in raw["tests"]:
        if test["id"] in seen:
            raise ProfileError("invalid_profile", f"duplicate test id {test['id']}")
        seen.add(test["id"])
        if test["control"] not in controls:
            raise ProfileError("invalid_profile", f"{test['id']} references unknown control {test['control']}")
    tested = {t["control"] for t in raw["tests"]}
    for cid in raw.get("applicability") or {}:
        if cid not in controls:
            raise ProfileError("invalid_profile", f"applicability references unknown control {cid}")
        if cid in tested:
            raise ProfileError("invalid_profile", f"{cid} has tests in this profile; an applicability exclusion cannot hide them")
    edges = (raw.get("coverage") or {}).get("dependency_edges", {})
    unknown = sorted(set(edges) - seen)
    if unknown:
        raise ProfileError("invalid_profile", f"coverage edges reference unknown tests {unknown}")


_normalized: dict[tuple[str, int | None], dict] = {}


def normalize(raw: dict, revision: int | None = None) -> dict:
    """Validated profile plus derived fields. Cached by content digest; callers must not mutate it."""
    digest = canonical_hash(raw)
    key = (digest, revision)
    if key in _normalized:
        return _normalized[key]
    validate(raw)
    data = json.loads(json.dumps(raw))
    data["controls"] = {cid: dict(meta) for cid, meta in control_catalog()["controls"].items()}
    data["digest"] = digest
    data["revision"] = revision
    for test in data["tests"]:
        test["digest"] = canonical_hash({k: v for k, v in test.items() if k != "digest"})[:16]
    data["tests_by_id"] = {t["id"]: t for t in data["tests"]}
    assessed = sorted({t["control"] for t in data["tests"]})
    data["assessed_controls"] = assessed
    data["unassessed_controls"] = sorted(set(data["controls"]) - set(assessed))
    declared = data.get("applicability") or {}  # `data` is a deep copy, so the stored profile is never mutated
    data["applicability"] = {cid: {**declared[cid], "reviewed": True} if cid in declared else {"status": "not_assessed", "reason": "", "reviewed": False}
                             for cid in data["unassessed_controls"]}
    data["not_applicable_controls"] = sorted(c for c, e in data["applicability"].items() if e["status"] == "not_applicable")
    _normalized[key] = data
    return data


def profile_version(p: dict) -> str:
    suffix = f"+r{p['revision']}" if p.get("revision") is not None else ""
    return f"{p['profile_id']}-{p['version']}{suffix}"


def load_profile_file(name: str) -> dict:
    path = settings().profiles_dir / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def reference_profile() -> dict:
    """The MCP reference application's profile, for fixtures and tooling."""
    return normalize(load_profile_file("refund-agent"))


def for_application(session: Session, application_id: str, *, revision: int | None = None) -> dict:
    """Active (or explicitly requested) profile revision of one application."""
    from .models import ApplicationProfile

    query = select(ApplicationProfile).where(ApplicationProfile.application_id == application_id)
    query = query.where(ApplicationProfile.revision == revision) if revision is not None else query.where(ApplicationProfile.status == "active")
    row = session.scalars(query.order_by(ApplicationProfile.revision.desc())).first()
    if row is None:
        raise ProfileError("no_profile", "this application has no active control profile; propose and review one first")
    return normalize(row.profile, row.revision)


def try_for_application(session: Session, application_id: str) -> dict | None:
    try:
        return for_application(session, application_id)
    except ProfileError:
        return None


def coverage_contract_for(p: dict) -> dict:
    """Coverage contract embedded in the profile or referenced by name."""
    if p.get("coverage"):
        return p["coverage"]
    if p.get("coverage_contract"):
        return load_coverage_contract(p["coverage_contract"])
    return {}


def load_coverage_contract(name: str) -> dict:
    return json.loads((settings().coverage_dir / f"{name}.json").read_text(encoding="utf-8"))


def profile_path(name: str) -> Path:
    return settings().profiles_dir / f"{name}.json"
