"""Application onboarding: connection revisions, verification, per-application profiles.

A connection pins the adapter, target origin, authorized scope and actor
credential references. A profile revision is proposed (from a file, the
template baseline or a model) and becomes active only through a different
reviewer; activation also records the reviewed dependency links and coverage
contract the reducer relies on.
"""

import hashlib
import hmac

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import vault
from .config import settings
from .models import Application, ApplicationProfile, Connection, CoverageContract, DependencyEdge, now
from .profile import ProfileError, canonical_hash, normalize


class OnboardingError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def adapters():
    from assureops_connectors import base

    return base


def latest_connection(session: Session, application_id: str) -> Connection | None:
    return session.scalars(select(Connection).where(Connection.application_id == application_id, Connection.status != "superseded")
                           .order_by(Connection.revision.desc())).first()


def create_connection(session: Session, app: Application, *, adapter_id: str, config: dict, actor: str) -> Connection:
    base = adapters()
    try:
        adapter = base.get(adapter_id)
    except base.AdapterError as exc:
        raise OnboardingError(exc.code, exc.detail)
    if hasattr(adapter, "validate_config"):
        problems = adapter.validate_config(config)
        if problems:
            raise OnboardingError("invalid_connection", "; ".join(problems))
    from assureops_connectors.egress import EgressDenied, check_target

    from .relay import is_relay

    try:  # a relay runs inside the customer's network, so its private target is authorized by them; metadata addresses never are
        check_target(config["base_url"], allow_private=settings().allow_private_targets or is_relay(config))
    except EgressDenied as exc:
        raise OnboardingError("destination_denied", str(exc))
    revision = (session.scalar(select(func.max(Connection.revision)).where(Connection.application_id == app.id)) or 0) + 1
    for old in session.scalars(select(Connection).where(Connection.application_id == app.id, Connection.status != "superseded")):
        old.status = "superseded"
    conn = Connection(workspace_id=app.workspace_id, application_id=app.id, revision=revision, adapter_id=adapter.adapter_id,
                      adapter_version=adapter.version, config=config, status="unverified", created_by=actor)
    session.add(conn)
    app.target_url = config["base_url"]
    if config.get("tools_url"):
        app.tools_url = config["tools_url"]
    session.flush()
    return conn


def spec_for(session: Session, conn: Connection, *, with_credentials: bool):
    base = adapters()
    creds, problems = ({}, [])
    if with_credentials:
        creds, problems = vault.credentials_for(session, conn.application_id, conn.config.get("actors") or {})
    from .relay import is_relay

    spec = base.ConnectionSpec(adapter_id=conn.adapter_id, revision=conn.revision, config=conn.config, credentials=creds,
                               allow_private=settings().allow_private_targets or is_relay(conn.config))
    return spec, problems


def verify(session: Session, app: Application, conn: Connection, p: dict | None) -> dict:
    """Run the adapter's connection checks and persist the result (status, checks, gaps, capabilities)."""
    if conn.status == "revoked":
        raise OnboardingError("revoked", "this connection was revoked")
    spec, problems = spec_for(session, conn, with_credentials=True)
    from . import relay

    if relay.is_relay(conn.config) and not problems:
        # The network checks run in the customer's relay; the profile-scope check runs here when its result arrives.
        task = relay.enqueue(session, workspace_id=conn.workspace_id, application_id=conn.application_id, kind="verify", ref_id=conn.id,
                             payload={"kind": "verify", "adapter_id": conn.adapter_id, "connection_revision": conn.revision, "config": conn.config,
                                      "credentials": spec.credentials, "allow_private": True},
                             deadline_seconds=600)
        conn.verification = {"status": "pending_relay", "relay_task": task.id, "checks": [], "gaps": ["waiting for the private connector to run the checks"]}
        conn.status = "pending_relay"
        return conn.verification
    result = adapters().get(conn.adapter_id).validate_connection(spec, p)
    if problems:
        result["checks"].append({"id": "credential_store", "status": "fail", "detail": "; ".join(problems)})
        result["status"] = "failed"
    conn.verification = result
    conn.status = result["status"]
    conn.verified_at = now()
    return result


def revoke_connection(session: Session, conn: Connection, actor: str) -> Connection:
    conn.status = "revoked"
    for ref in (conn.config.get("actors") or {}).values():
        if ref.get("secret_id"):
            try:
                vault.revoke(session, ref["secret_id"], actor)
            except vault.VaultError:
                pass
    return conn


def require_verified(session: Session, application_id: str) -> Connection:
    conn = latest_connection(session, application_id)
    if conn is None:
        raise OnboardingError("not_connected", "connect the application before collecting releases or running tests")
    if conn.status != "verified":
        raise OnboardingError("connection_unverified", f"connection revision {conn.revision} is {conn.status}; verify it first")
    return conn


# ---------------- profiles ----------------

def _template_check(p: dict, adapter_id: str):
    if adapter_id == "assureops-mcp-reference":
        return
    from assureops_connectors import templates

    for test in p["tests"]:
        try:
            templates.validate_args(test["template"], test["args"])
            if test["template"] != "manifest_identity":
                templates.expand(test["template"], test["args"])
        except templates.TemplateError as exc:
            raise OnboardingError("invalid_profile", f"{test['id']}: {exc}")


def propose_profile(session: Session, app: Application, raw: dict, *, source: str, actor: str) -> ApplicationProfile:
    try:
        p = normalize(raw)
    except ProfileError as exc:
        raise OnboardingError(exc.code, exc.detail)
    _template_check(p, raw["adapter"])
    conn = latest_connection(session, app.id)
    if conn is not None and conn.adapter_id != adapters().get(raw["adapter"]).adapter_id:
        raise OnboardingError("adapter_mismatch", f"profile targets {raw['adapter']}, the connection uses {conn.adapter_id}")
    revision = (session.scalar(select(func.max(ApplicationProfile.revision)).where(ApplicationProfile.application_id == app.id)) or 0) + 1
    row = ApplicationProfile(workspace_id=app.workspace_id, application_id=app.id, revision=revision, profile=raw, digest=canonical_hash(raw),
                             status="proposed", source=source, proposed_by=actor)
    session.add(row)
    session.flush()
    return row


def activate_profile(session: Session, app: Application, revision: int, *, reviewer: str, note: str,
                     allow_same_person: bool = False) -> ApplicationProfile:
    row = session.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id, ApplicationProfile.revision == revision)
                          .with_for_update()).first()
    if row is None:
        raise OnboardingError("not_found", "profile revision not found")
    if row.status != "proposed":
        raise OnboardingError("invalid_state", f"profile revision {revision} is {row.status}")
    if row.proposed_by == reviewer and not allow_same_person:
        raise OnboardingError("separation_of_duties", "the person who proposed a profile cannot activate it")
    if not note.strip():
        raise OnboardingError("note_required", "a review note is required")
    for old in session.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id, ApplicationProfile.status == "active")):
        old.status = "superseded"
    row.status, row.reviewed_by, row.review_note, row.activated_at = "active", reviewer, note, now()
    p = normalize(row.profile, row.revision)
    _apply_coverage(session, app, p, reviewer)
    session.flush()
    return row


def reject_profile(session: Session, app: Application, revision: int, *, reviewer: str, note: str) -> ApplicationProfile:
    row = session.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id, ApplicationProfile.revision == revision)).first()
    if row is None or row.status != "proposed":
        raise OnboardingError("invalid_state", "only a proposed revision can be rejected")
    row.status, row.reviewed_by, row.review_note = "rejected", reviewer, note
    return row


def _apply_coverage(session: Session, app: Application, p: dict, reviewer: str):
    """Record the profile's reviewed coverage contract and dependency links; keep analyst decisions on existing links."""
    from .profile import coverage_contract_for

    contract = coverage_contract_for(p)
    if not contract:
        return
    revision = (session.scalar(select(func.max(CoverageContract.revision)).where(CoverageContract.application_id == app.id)) or 0) + 1
    session.add(CoverageContract(workspace_id=app.workspace_id, application_id=app.id, revision=revision, contract=contract,
                                 reviewer=contract.get("reviewer", reviewer)))
    existing = {(e.test_id, e.component_id): e for e in session.scalars(select(DependencyEdge).where(DependencyEdge.application_id == app.id))}
    for test_id, comps in contract.get("dependency_edges", {}).items():
        for cid in comps:
            if (test_id, cid) in existing:
                continue
            session.add(DependencyEdge(workspace_id=app.workspace_id, application_id=app.id, test_id=test_id, component_id=cid, status="accepted",
                                       source="coverage_contract", rationale=f"Reviewed link in profile {p['profile_id']} {p['version']}",
                                       reviewer=reviewer))


# ---------------- run tokens ----------------

def run_tokens(step_id: str, trials: int) -> list[str]:
    """Unforgeable per-trial tokens (HMAC with a platform key the runner never sees)."""
    key = (settings().run_token_key or settings().secret_key or "dev").encode()
    return ["ao-" + hmac.new(key, f"{step_id}:{i}".encode(), hashlib.sha256).hexdigest()[:12] for i in range(trials)]


def apply_relay_verification(session: Session, conn: Connection, result: dict, p: dict | None) -> dict:
    """Store a relay's network checks and add the platform-side profile-scope check (static, no network).

    The status is recomputed here from the checks; a relay's own status label is never trusted.
    """
    checks = [c for c in (result.get("checks") or []) if isinstance(c, dict) and c.get("status") in ("pass", "fail", "gap")]
    if not checks:
        checks = [{"id": "relay", "status": "fail", "detail": "the relay returned no connection checks"}]
    out = {"checks": checks, "gaps": sorted({str(g) for g in (result.get("gaps") or [])}),
           "capabilities": dict(result.get("capabilities") or {}), "executed_by": "relay"}
    adapter = adapters().get(conn.adapter_id)
    if p is not None and hasattr(adapter, "profile_compatibility"):
        spec, _ = spec_for(session, conn, with_credentials=False)
        blocked = adapter.profile_compatibility(spec, p)
        out["capabilities"].update(tests_runnable=len(p["tests"]) - len(blocked), tests_blocked=blocked)
        out["checks"].append({"id": "profile_scope", "status": "fail" if blocked else "pass",
                              "detail": f"{len(blocked)} tests cannot run within this connection" if blocked else "every profile test fits the authorized scope"})
    out["status"] = "failed" if any(c["status"] == "fail" for c in out["checks"]) else "verified"
    conn.verification, conn.status, conn.verified_at = out, out["status"], now()
    return out
