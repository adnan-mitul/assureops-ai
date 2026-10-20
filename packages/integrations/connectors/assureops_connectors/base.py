"""Versioned connector adapter contract (integration plan I2).

Every adapter implements the same five operations. Adapters never decide
outcomes beyond the deterministic assertions of an approved test; the
backend's reducer and reviewers decide readiness.
"""

from dataclasses import dataclass, field

MANIFEST_REQUIRED = {"schema_version", "application", "release", "components", "collection"}


class AdapterError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class ConnectionSpec:
    """Connection configuration plus, inside a runner only, the decrypted actor credentials."""

    adapter_id: str
    revision: int
    config: dict
    credentials: dict[str, str] = field(default_factory=dict)
    allow_private: bool = False

    @property
    def base_url(self) -> str:
        return self.config["base_url"]


@dataclass
class TestContext:
    __test__ = False
    step_id: str
    release_version: str
    frozen_manifest: dict
    run_tokens: list[str]
    marker_header: str = "X-AssureOps-Test"


class Adapter:
    adapter_id = "abstract"
    version = "0"
    evaluator_version = "0"

    def collect_manifest(self, spec: ConnectionSpec) -> dict:
        raise NotImplementedError

    def validate_connection(self, spec: ConnectionSpec, profile: dict | None) -> dict:
        raise NotImplementedError

    def run_allowed_test(self, spec: ConnectionSpec, test: dict, ctx: TestContext) -> tuple[bool, dict]:
        raise NotImplementedError

    def read_action_evidence(self, spec: ConnectionSpec, query: dict) -> dict:
        raise NotImplementedError

    def normalize_event(self, spec: ConnectionSpec, raw: dict, *, source_id: str, epoch: str) -> dict:
        raise NotImplementedError


def check_manifest(manifest) -> list[str]:
    """Structural problems with a collected manifest (empty list when acceptable)."""
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]
    problems = [f"missing {k}" for k in sorted(MANIFEST_REQUIRED - set(manifest))]
    comps = manifest.get("components")
    if not isinstance(comps, dict) or not comps:
        problems.append("components must be a non-empty object")
    else:
        for cid, comp in comps.items():
            if not isinstance(comp, dict) or not comp.get("fingerprint") or not comp.get("type"):
                problems.append(f"component {cid} lacks type/fingerprint")
    if not isinstance(manifest.get("release"), str) or not manifest.get("release"):
        problems.append("release must be a non-empty string")
    return problems


_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter, *aliases: str):
    for key in (adapter.adapter_id, *aliases):
        _REGISTRY[key] = adapter


def _load():
    from . import http_json, mcp_reference  # noqa: F401  each registers itself on first import


def get(adapter_id: str) -> Adapter:
    _load()
    if adapter_id not in _REGISTRY:
        raise AdapterError("unsupported_adapter", f"adapter {adapter_id!r} is not supported")
    return _REGISTRY[adapter_id]


def supported() -> list[dict]:
    _load()
    seen, out = set(), []
    for key, adapter in _REGISTRY.items():
        if id(adapter) in seen:
            continue
        seen.add(id(adapter))
        out.append({"adapter_id": adapter.adapter_id, "version": adapter.version, "evaluator_version": adapter.evaluator_version,
                    "aliases": [k for k, a in _REGISTRY.items() if a is adapter and k != adapter.adapter_id]})
    return out
