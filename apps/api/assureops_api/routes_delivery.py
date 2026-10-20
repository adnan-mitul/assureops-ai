"""Customer CI/CD integration: exact-SHA release gate, expiring deployment receipts, GitHub App webhooks.

A gate decision binds one commit SHA (and optional artifact digest) to one
assessed release. A different commit never inherits it. Receipts expire and are
re-validated on every verification: a changed active profile, a newer release,
new evidence state or any incident opened after issue invalidates them.
"""

import hashlib
import hmac
import json
import secrets
import time

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases, reducer
from assureops_domain.config import settings
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import (
    Application, DeploymentReceipt, GithubDelivery, Incident, Release, RepositoryBinding, RepositoryRoute, ServiceCredential,
)
from assureops_domain.profile import try_for_application

from . import services as svc
from .auth import Caller, CustomerCaller, Service, api_error, service, token_hash

router = APIRouter(prefix="/v1", tags=["delivery"])
STATUS_CONTEXT = "assureops/release-gate"


def _status_token() -> str | None:
    """Server-side token allowed to write commit statuses (GITHUB_STATUS_TOKEN); development may reuse the git credential."""
    import os
    import subprocess

    from assureops_domain.config import _dev_env

    token = os.environ.get("GITHUB_STATUS_TOKEN") or _dev_env().get("GITHUB_STATUS_TOKEN")
    if token:
        return token
    if (os.environ.get("GITHUB_STATUS_FROM_GIT") or _dev_env().get("GITHUB_STATUS_FROM_GIT")) == "true":
        out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True)
        return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line).get("password")
    return None


def post_commit_status(repository: str, sha: str, decision: str, reasons: list[str], transport=None) -> dict:
    """Publish the exact-SHA gate decision as a GitHub commit status. Without a token the decision is only served by the API."""
    import httpx

    token = _status_token()
    if not token:
        return {"posted": False, "reason": "no status token configured"}
    state = "success" if decision == "allow" else "failure"
    description = ("Assessed and ready" if decision == "allow" else "; ".join(reasons) or "not ready")[:140]
    with httpx.Client(transport=transport, timeout=10, trust_env=False) as http:
        res = http.post(f"https://api.github.com/repos/{repository}/statuses/{sha}",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                        json={"state": state, "context": STATUS_CONTEXT, "description": description})
    return {"posted": res.status_code == 201, "status_code": res.status_code, "state": state, "context": STATUS_CONTEXT}


def _sign(payload: dict) -> str:
    key = (settings().receipt_signing_key or settings().secret_key).encode()
    return hmac.new(key, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()


def _receipt_payload(r: DeploymentReceipt) -> dict:
    return {"id": r.id, "application_id": r.application_id, "release_id": r.release_id, "commit_sha": r.commit_sha,
            "artifact_digest": r.artifact_digest, "profile_digest": r.profile_digest, "decision": r.decision,
            "issued_at": round(r.issued_at, 3), "expires_at": round(r.expires_at, 3)}


def evaluate(s, app: Application, commit_sha: str, artifact_digest: str | None) -> tuple[dict, Release | None]:
    release = s.scalars(select(Release).where(Release.application_id == app.id, Release.source_commit == commit_sha)
                        .order_by(Release.created_at.desc())).first()
    p = try_for_application(s, app.id)
    if release is None:
        return {"decision": "deny", "reasons": [f"commit {commit_sha[:12]} has no assessed release; submit it with this exact SHA"]}, None
    reasons = []
    if artifact_digest and release.artifact_digest and artifact_digest != release.artifact_digest:
        reasons.append("artifact digest differs from the assessed artifact")
    if artifact_digest and not release.artifact_digest:
        reasons.append("assessed release recorded no artifact digest; the deployed artifact cannot be matched")
    latest = svc.latest_release(s, app.id)
    if latest.id != release.id:
        reasons.append(f"a newer release ({latest.version}) was collected after this commit")
    if p is None:
        return {"decision": "deny", "reasons": ["no active profile"]}, release
    state = reducer.readiness(s, app.id, release, p)
    if state["gate"]["status"] != "ready":
        reasons.append(f"gate is {state['gate']['status']}: {state['gate']['reason']}")
    open_incidents = s.scalars(select(Incident).where(Incident.application_id == app.id, Incident.state == "open")).all()
    if open_incidents:
        reasons.append(f"{len(open_incidents)} open runtime incident(s)")
    return {"decision": "deny" if reasons else "allow", "reasons": reasons, "gate": state["gate"], "scores": state["scores"],
            "release": release.version, "profile": state["profile"]["version"], "profile_digest": p["digest"],
            "unassessed_controls": state["gate"]["unassessed"]}, release


class GateIn(BaseModel):
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    artifact_digest: str | None = Field(default=None, max_length=100)


def ci_service(svc_: Service = Depends(service("ci"))) -> Service:
    return svc_


@router.post("/integration/release-gate/check")
def gate_check(body: GateIn, svc_: Service = Depends(ci_service)):
    """Called by the customer's pipeline with a CI credential bound to one application."""
    with tenant_session(svc_.workspace_id) as s:
        app = s.get(Application, svc_.application_id)
        result, release = evaluate(s, app, body.commit_sha, body.artifact_digest)
        if release is None:
            return {**result, "receipt": None}
        receipt = DeploymentReceipt(workspace_id=app.workspace_id, application_id=app.id, release_id=release.id, commit_sha=body.commit_sha,
                                    artifact_digest=body.artifact_digest, profile_digest=result.get("profile_digest", ""), decision=result["decision"],
                                    gate={k: result.get(k) for k in ("gate", "reasons", "release", "profile")}, signature="",
                                    expires_at=time.time() + settings().receipt_ttl_seconds)
        s.add(receipt)
        s.flush()
        receipt.signature = _sign(_receipt_payload(receipt))
        cases.audit(s, workspace_id=app.workspace_id, actor=f"ci:{svc_.application_id}", actor_kind="service", action="gate.check",
                    target=body.commit_sha, detail={"decision": result["decision"], "receipt": receipt.id})
        return {**{k: v for k, v in result.items() if k != "profile_digest"},
                "receipt": {**_receipt_payload(receipt), "signature": receipt.signature}}


class VerifyIn(BaseModel):
    receipt_id: str
    signature: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


@router.post("/integration/release-gate/verify")
def verify_receipt(body: VerifyIn, svc_: Service = Depends(ci_service)):
    """Deployment-time check: the receipt must still be valid for this exact commit right now."""
    with tenant_session(svc_.workspace_id) as s:
        r = s.get(DeploymentReceipt, body.receipt_id)
        if r is None or r.application_id != svc_.application_id:
            raise api_error(404, "not_found", "receipt not found")
        problems = []
        if not hmac.compare_digest(body.signature, r.signature) or _sign(_receipt_payload(r)) != r.signature:
            problems.append("signature invalid")
        if body.commit_sha != r.commit_sha:
            problems.append("receipt was issued for a different commit")
        if r.decision != "allow":
            problems.append("receipt records a deny decision")
        if time.time() > r.expires_at:
            problems.append("receipt expired")
        if r.invalidated_at:
            problems.append(f"receipt invalidated: {r.invalidation_reason}")
        p = try_for_application(s, r.application_id)
        if p is None or p["digest"] != r.profile_digest:
            problems.append("the active profile changed since the receipt was issued")
        newer = s.scalars(select(Incident).where(Incident.application_id == r.application_id, Incident.created_at > r.issued_at)).first()
        if newer:
            problems.append("an incident was opened after the receipt was issued")
        latest = svc.latest_release(s, r.application_id)
        if latest is None or latest.id != r.release_id:
            problems.append("a newer release was collected after the receipt was issued")
        if problems and not r.invalidated_at and r.decision == "allow" and "signature invalid" not in problems:
            r.invalidated_at, r.invalidation_reason = time.time(), "; ".join(problems)
        return {"valid": not problems, "problems": problems, "receipt": _receipt_payload(r)}


# ---------------- Credentials and repository bindings (owner) ----------------

@router.post("/applications/{application_id}/ci-credentials", status_code=201)
def issue_ci_credential(application_id: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with tenant_session(caller.workspace_id) as s:
        app = svc.get_application(s, application_id)
        environment = app.environment
    token = "aoci_" + secrets.token_urlsafe(32)
    with platform_session() as p:
        p.add(ServiceCredential(kind="ci", workspace_id=caller.workspace_id, application_id=application_id, environment=environment,
                                token_hash=token_hash(token)))
    with tenant_session(caller.workspace_id) as s:
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="ci_credential.issue", target=application_id)
    return {"token": token, "note": "Store as a CI secret (for example ASSUREOPS_CI_TOKEN); it is not shown again."}


class RepoIn(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    installation_id: str | None = None


@router.post("/applications/{application_id}/repositories", status_code=201)
def bind_repository(application_id: str, body: RepoIn, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with platform_session() as p:
        route = p.get(RepositoryRoute, body.repository.lower())
        if route and (route.workspace_id, route.application_id) != (caller.workspace_id, application_id):
            raise api_error(409, "repository_bound", "this repository is bound to another application")
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        s.add(RepositoryBinding(workspace_id=caller.workspace_id, application_id=application_id, repository=body.repository.lower(),
                                installation_id=body.installation_id, created_by=caller.username))
    with platform_session() as p:
        if not p.get(RepositoryRoute, body.repository.lower()):
            p.add(RepositoryRoute(repository=body.repository.lower(), workspace_id=caller.workspace_id, application_id=application_id))
    return {"repository": body.repository.lower(), "application_id": application_id}


# ---------------- GitHub App webhook ----------------

@router.post("/integration/github/webhook")
async def github_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None),
                         x_github_event: str | None = Header(default=None), x_github_delivery: str | None = Header(default=None)):
    """Signature-verified, deduplicated. Records the exact SHA for a bound repository; gate checks run per commit."""
    secret = settings().github_webhook_secret
    raw = await request.body()
    if not secret:
        raise api_error(503, "not_configured", "GitHub App webhook secret is not configured")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise api_error(401, "bad_signature", "webhook signature verification failed")
    if not x_github_delivery:
        raise api_error(422, "missing_delivery", "X-GitHub-Delivery header required")
    with platform_session() as p:
        if p.get(GithubDelivery, x_github_delivery):
            return {"status": "duplicate"}
        p.add(GithubDelivery(id=x_github_delivery, event=x_github_event or "unknown"))
    payload = json.loads(raw or b"{}")
    repo = ((payload.get("repository") or {}).get("full_name") or "").lower()
    sha = payload.get("after") or (payload.get("deployment") or {}).get("sha") or ((payload.get("check_suite") or {}).get("head_sha"))
    with platform_session() as p:
        route = p.get(RepositoryRoute, repo) if repo else None
    if route is None:
        return {"status": "ignored", "reason": "repository is not bound to an application"}
    with tenant_session(route.workspace_id) as s:
        app = s.get(Application, route.application_id)
        result, release = evaluate(s, app, sha, None) if sha and len(sha) == 40 else ({"decision": "deny", "reasons": ["no commit SHA"]}, None)
        cases.audit(s, workspace_id=route.workspace_id, actor=f"github:{repo}", actor_kind="service", action=f"github.{x_github_event}",
                    target=sha or "-", detail={"decision": result["decision"], "reasons": result.get("reasons", [])})
    status = post_commit_status(repo, sha, result["decision"], result.get("reasons", [])) if sha and len(sha) == 40 else {"posted": False}
    return {"status": "evaluated", "event": x_github_event, "commit_sha": sha, "decision": result["decision"], "reasons": result.get("reasons", []),
            "commit_status": status}
