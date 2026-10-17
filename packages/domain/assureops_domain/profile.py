"""Versioned control profile and adapter coverage contracts."""

import hashlib
import json
from functools import lru_cache

from .config import settings

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

COMPONENT_LABELS = {
    "prompt": "Prompt update", "model": "Model update", "policy": "Policy change", "tool": "Tool schema change",
    "tools": "Tool registry change", "config": "Config change", "corpus": "Corpus update", "code": "Code update",
    "protocol": "Protocol change",
}


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache
def profile() -> dict:
    data = json.loads(settings().profile_path.read_text())
    data["digest"] = canonical_hash(data)
    data["tests_by_id"] = {t["id"]: t for t in data["tests"]}
    return data


def profile_version() -> str:
    p = profile()
    return f"{p['profile_id']}-{p['version']}"


def load_coverage_contract(name: str) -> dict:
    return json.loads((settings().coverage_dir / f"{name}.json").read_text())
