"""Customer onboarding surface: connections, target credentials, per-application profiles, evidence lifecycle.

Credentials arrive once in a request body, are encrypted into the connector
secret store and are never returned; responses carry only fingerprints.
"""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases, connections, evidence_store, vault
from assureops_domain.db import tenant_session
from assureops_domain.models import ApplicationProfile, Artifact, Release, TestRun
from assureops_domain.profile import ProfileError, normalize

from . import services as svc
from .access import require_application_writer
from .auth import Caller, CustomerCaller, api_error

router = APIRouter(prefix="/v1", tags=["onboarding"])
WRITE_ROLES = ("owner", "developer")


def audit(s, caller: Caller, action: str, target: str, detail: dict | None = None):
    cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action=action, target=target, detail=detail)


def _onboarding_error(exc):
    status = {"separation_of_duties": 403, "not_found": 404, "destination_denied": 422, "invalid_connection": 422, "invalid_profile": 422,
              "vault_unconfigured": 503}.get(exc.code, 409)
    return api_error(status, exc.code, exc.detail)


@router.get("/connectors/adapters")
def list_adapters(caller: Caller = CustomerCaller):
    base = connections.adapters()
    from assureops_connectors import templates

    return {"adapters": base.supported(), "templates": templates.catalogue()}


# ---------------- Connection ----------------

class ActorCredentialIn(BaseModel):
    secret_value: str | None = Field(default=None, min_length=1, max_length=4096)
    secret_id: str | None = None


class ConnectionIn(BaseModel):
    adapter_id: str
    config: dict
    actors: dict[str, ActorCredentialIn] = Field(default_factory=dict)


@router.post("/applications/{application_id}/connection", status_code=201)
def create_connection(application_id: str, body: ConnectionIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES)
    if "actors" in body.config:
        raise api_error(422, "invalid_connection", "send credentials in `actors`, not inside config")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        refs = {}
        try:
            for name, cred in body.actors.items():
                if not name.replace("_", "").replace("-", "").isalnum() or name in ("anonymous", "invalid"):
                    raise api_error(422, "invalid_actor", f"actor name {name!r} is reserved or invalid")
                if cred.secret_value:
                    row = vault.store(s, workspace_id=app.workspace_id, application_id=app.id, name=f"{app.id}:{name}",
                                      value=cred.secret_value, actor=caller.username)
                    refs[name] = {"secret_id": row.id}
                elif cred.secret_id:
                    refs[name] = {"secret_id": cred.secret_id}
                else:
                    raise api_error(422, "invalid_actor", f"actor {name} needs a credential")
            conn = connections.create_connection(s, app, adapter_id=body.adapter_id, config={**body.config, "actors": refs}, actor=caller.username)
        except (connections.OnboardingError, vault.VaultError) as exc:
            raise _onboarding_error(exc)
        audit(s, caller, "connection.create", app.id, {"revision": conn.revision, "adapter": conn.adapter_id, "actors": sorted(refs)})
        return svc.connection_json(s, app)


@router.get("/applications/{application_id}/connection")
def get_connection(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        data = svc.connection_json(s, app)
        if data is None:
            raise api_error(404, "not_connected", "this application has no connection yet")
        return data


@router.post("/applications/{application_id}/connection/verify")
def verify_connection(application_id: str, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        conn = connections.latest_connection(s, app.id)
        if conn is None:
            raise api_error(404, "not_connected", "this application has no connection yet")
        p = _profile_for_verification(s, app.id)
        try:
            result = connections.verify(s, app, conn, p)
        except connections.OnboardingError as exc:
            raise _onboarding_error(exc)
        audit(s, caller, "connection.verify", app.id, {"revision": conn.revision, "status": result["status"]})
        return {**svc.connection_json(s, app), "profile_checked": p["profile_id"] + "-" + p["version"] if p else None}


def _profile_for_verification(s, application_id: str) -> dict | None:
    row = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == application_id,
                                                     ApplicationProfile.status.in_(["active", "proposed"]))
                    .order_by(ApplicationProfile.status.asc(), ApplicationProfile.revision.desc())).first()
    return normalize(row.profile, row.revision) if row else None


@router.post("/applications/{application_id}/connection/revoke")
def revoke_connection(application_id: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        conn = connections.latest_connection(s, app.id)
        if conn is None:
            raise api_error(404, "not_connected", "nothing to revoke")
        connections.revoke_connection(s, conn, caller.username)
        audit(s, caller, "connection.revoke", app.id, {"revision": conn.revision})
        return svc.connection_json(s, app)


# ---------------- Profiles ----------------

@router.get("/applications/{application_id}/profiles")
def list_profiles(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        rows = s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == application_id)
                         .order_by(ApplicationProfile.revision.desc())).all()
        return [svc.profile_row_json(r) for r in rows]


class ProfileIn(BaseModel):
    profile: dict


@router.post("/applications/{application_id}/profiles", status_code=201)
def propose_profile(application_id: str, body: ProfileIn, caller: Caller = CustomerCaller):
    caller.require_role(*WRITE_ROLES)
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        try:
            row = connections.propose_profile(s, app, body.profile, source="analyst", actor=caller.username)
        except connections.OnboardingError as exc:
            raise _onboarding_error(exc)
        audit(s, caller, "profile.propose", app.id, {"revision": row.revision})
        return svc.profile_row_json(row)


class BaselineIn(BaseModel):
    hints: dict


@router.post("/applications/{application_id}/profiles/baseline", status_code=201)
def propose_baseline(application_id: str, body: BaselineIn, caller: Caller = CustomerCaller):
    """Template-based starter profile from declared facts; it still needs an independent review."""
    caller.require_role(*WRITE_ROLES)
    from assureops_connectors import baseline, templates

    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        require_application_writer(s, caller, app.id)
        release = svc.latest_release(s, app.id)
        conn = connections.latest_connection(s, app.id)
        components = sorted(release.manifest["components"]) if release else []
        if not components and conn is not None:
            spec, _ = connections.spec_for(s, conn, with_credentials=False)
            try:
                components = sorted(connections.adapters().get(conn.adapter_id).collect_manifest(spec)["manifest"]["components"])
            except connections.adapters().AdapterError:
                components = []
        try:
            raw = baseline.propose(body.hints, profile_id=f"{app.id}-baseline"[:60], components=components)
            row = connections.propose_profile(s, app, raw, source="template", actor=caller.username)
        except templates.TemplateError as exc:
            raise api_error(422, "invalid_hints", str(exc))
        except connections.OnboardingError as exc:
            raise _onboarding_error(exc)
        audit(s, caller, "profile.baseline", app.id, {"revision": row.revision, "tests": len(raw["tests"])})
        return svc.profile_row_json(row)


class ProfileDecisionIn(BaseModel):
    note: str = Field(min_length=3)


@router.post("/applications/{application_id}/profiles/{revision}/activate")
def activate_profile(application_id: str, revision: int, body: ProfileDecisionIn, caller: Caller = CustomerCaller):
    caller.require_role("owner", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        try:
            row = connections.activate_profile(s, app, revision, reviewer=caller.username, note=body.note)
        except connections.OnboardingError as exc:
            raise _onboarding_error(exc)
        except ProfileError as exc:
            raise api_error(422, exc.code, exc.detail)
        audit(s, caller, "profile.activate", app.id, {"revision": revision})
        return svc.profile_row_json(row)


@router.post("/applications/{application_id}/profiles/{revision}/reject")
def reject_profile(application_id: str, revision: int, body: ProfileDecisionIn, caller: Caller = CustomerCaller):
    caller.require_role("owner", "reviewer")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        try:
            row = connections.reject_profile(s, app, revision, reviewer=caller.username, note=body.note)
        except connections.OnboardingError as exc:
            raise _onboarding_error(exc)
        audit(s, caller, "profile.reject", app.id, {"revision": revision})
        return svc.profile_row_json(row)


# ---------------- Evidence lifecycle ----------------

@router.get("/evidence/{run_id}/download")
def download_evidence(run_id: str, caller: Caller = CustomerCaller):
    """Authorized download of the exact stored bytes; integrity is verified before sending."""
    with tenant_session(caller.workspace_id) as s:
        run = s.get(TestRun, run_id)
        if run is None:
            raise api_error(404, "not_found", "evidence not found")
        artifact = s.get(Artifact, run.artifact_id)
        try:
            data = evidence_store.read_bytes(artifact)
        except evidence_store.EvidenceUnavailable as exc:
            raise api_error(410, "evidence_unavailable", str(exc))
        audit(s, caller, "evidence.download", run.id, {"sha256": artifact.sha256})
    return Response(content=data, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}.json"', "X-Evidence-SHA256": artifact.sha256,
                             "Cache-Control": "no-store"})


class DeletionIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/evidence/{run_id}/delete")
def delete_evidence(run_id: str, body: DeletionIn, caller: Caller = CustomerCaller):
    """Owner-requested erasure. The run stays as metadata; its controls become unavailable and need fresh evidence."""
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        run = s.get(TestRun, run_id)
        if run is None:
            raise api_error(404, "not_found", "evidence not found")
        artifact = s.get(Artifact, run.artifact_id)
        if artifact.deleted_at is not None:
            raise api_error(409, "already_deleted", "evidence bytes were already deleted")
        evidence_store.tombstone(s, artifact, actor=caller.username, reason=body.reason)
        audit(s, caller, "evidence.delete", run.id, {"sha256": artifact.sha256, "reason": body.reason})
        return {"run_id": run.id, "deleted": True}


@router.get("/evidence-deletions")
def evidence_deletions(caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        return evidence_store.deletion_history(s)


@router.get("/applications/{application_id}/releases/{release_id}/manifest")
def release_manifest(application_id: str, release_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        release = s.get(Release, release_id)
        if release is None or release.application_id != application_id:
            raise api_error(404, "not_found", "release not found")
        return release.manifest


# ---------------- Runtime event sources ----------------

class EventSourceIn(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    kind: str = Field(pattern=r"^(application|agent|tool_server|gateway)$")
    environment: str = Field(default="staging", pattern=r"^(staging|production)$")


@router.post("/applications/{application_id}/event-sources", status_code=201)
def create_event_source(application_id: str, body: EventSourceIn, caller: Caller = CustomerCaller):
    """Issue a source credential bound to one application and environment. The token is shown exactly once."""
    import secrets as _secrets

    from assureops_domain.db import platform_session
    from assureops_domain.models import EventSource

    from .auth import token_hash

    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
    token = "aos_" + _secrets.token_urlsafe(32)
    with platform_session() as p:
        if p.get(EventSource, body.source_id):
            raise api_error(409, "exists", "source id already registered")
        p.add(EventSource(id=body.source_id, workspace_id=caller.workspace_id, application_id=application_id, environment=body.environment,
                          kind=body.kind, token_hash=token_hash(token)))
    with tenant_session(caller.workspace_id) as s:
        audit(s, caller, "event_source.create", body.source_id, {"kind": body.kind, "environment": body.environment})
    return {"source_id": body.source_id, "kind": body.kind, "environment": body.environment, "token": token,
            "note": "Store this token in the bridge's secret store now; it is not shown again."}


@router.get("/applications/{application_id}/event-sources")
def list_event_sources(application_id: str, caller: Caller = CustomerCaller):
    from assureops_domain.db import platform_session
    from assureops_domain.models import EventSource

    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
    with platform_session() as p:
        return [{"source_id": e.id, "kind": e.kind, "environment": e.environment, "revoked": e.revoked}
                for e in p.scalars(select(EventSource).where(EventSource.workspace_id == caller.workspace_id, EventSource.application_id == application_id))]


@router.post("/applications/{application_id}/event-sources/{source_id}/revoke")
def revoke_event_source(application_id: str, source_id: str, caller: Caller = CustomerCaller):
    from assureops_domain.db import platform_session
    from assureops_domain.models import EventSource

    caller.require_role("owner")
    with platform_session() as p:
        src = p.get(EventSource, source_id)
        if src is None or src.workspace_id != caller.workspace_id or src.application_id != application_id:
            raise api_error(404, "not_found", "event source not found")
        src.revoked = True
    with tenant_session(caller.workspace_id) as s:
        audit(s, caller, "event_source.revoke", source_id)
    return {"source_id": source_id, "revoked": True}


# ---------------- Source/build analysis (REA or built-in collector) ----------------

class SnapshotIn(BaseModel):
    zip_base64: str = Field(min_length=20, max_length=11_000_000)
    code_map: dict[str, str] = Field(default_factory=dict, description="manifest component ID -> path in the snapshot whose hash it fingerprints")


@router.post("/applications/{application_id}/releases/{release_id}/source-analyses", status_code=202)
def analyze_snapshot(application_id: str, release_id: str, body: SnapshotIn, caller: Caller = CustomerCaller):
    """Store an authorized source snapshot privately and queue analysis; source is never executed."""
    import base64
    import binascii

    from assureops_domain.models import AnalysisRun, Outbox

    caller.require_role(*WRITE_ROLES)
    try:
        data = base64.b64decode(body.zip_base64, validate=True)
    except (binascii.Error, ValueError):
        raise api_error(422, "invalid_snapshot", "zip_base64 is not valid base64")
    if not data.startswith(b"PK"):
        raise api_error(422, "invalid_snapshot", "snapshot must be a zip archive")
    with tenant_session(caller.workspace_id) as s:
        release = s.get(Release, release_id)
        if release is None or release.application_id != application_id:
            raise api_error(404, "not_found", "release not found")
        require_application_writer(s, caller, application_id)
        artifact = evidence_store.put_bytes(s, caller.workspace_id, data, "application/zip")
        run = AnalysisRun(workspace_id=caller.workspace_id, application_id=application_id, release_id=release.id, snapshot_artifact_id=artifact.id,
                          snapshot_sha256=artifact.sha256, code_map=body.code_map, requested_by=caller.username)
        s.add(run)
        s.flush()
        s.add(Outbox(workspace_id=caller.workspace_id, kind="source_analysis", ref_id=run.id))
        audit(s, caller, "source.analyze", run.id, {"release": release.version, "sha256": artifact.sha256})
        return {"id": run.id, "status": run.status, "snapshot_sha256": artifact.sha256}


@router.get("/applications/{application_id}/source-analyses")
def list_analyses(application_id: str, caller: Caller = CustomerCaller):
    from assureops_domain.models import AnalysisRun

    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        rows = s.scalars(select(AnalysisRun).where(AnalysisRun.application_id == application_id).order_by(AnalysisRun.created_at.desc())).all()
        return [{"id": r.id, "release_id": r.release_id, "status": r.status, "analyzer": r.analyzer, "snapshot_sha256": r.snapshot_sha256,
                 "summary": r.summary, "error": r.error, "created_at": r.created_at, "finished_at": r.finished_at} for r in rows]
