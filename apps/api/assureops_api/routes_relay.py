"""Private connector (relay): owner-issued, application-bound credentials and the outbound-only claim/result protocol."""

import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from assureops_domain import cases, connections, relay
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Connection, RelayTask, ServiceCredential
from assureops_domain.profile import try_for_application

from . import services as svc
from .auth import Caller, CustomerCaller, Service, api_error, service, token_hash

router = APIRouter(prefix="/v1", tags=["relay"])


def relay_service(svc_: Service = Depends(service("relay"))) -> Service:
    return svc_


# ---------------- Customer: relay credentials ----------------

class RelayCredentialIn(BaseModel):
    environment: str = Field(default="staging", pattern=r"^(staging|production)$")


@router.post("/applications/{application_id}/relay-credentials", status_code=201)
def issue_relay_credential(application_id: str, body: RelayCredentialIn | None = None, caller: Caller = CustomerCaller):
    """The token is shown exactly once; the relay stores it in the customer's own secret store."""
    caller.require_role("owner")
    env = (body or RelayCredentialIn()).environment
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
    token = "aorl_" + secrets.token_urlsafe(32)
    with platform_session() as p:
        cred = ServiceCredential(kind="relay", workspace_id=caller.workspace_id, application_id=application_id, environment=env,
                                 token_hash=token_hash(token))
        p.add(cred)
        p.flush()
        cred_id = cred.id
    with tenant_session(caller.workspace_id) as s:
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="relay.credential.issue",
                    target=cred_id, detail={"application": application_id, "environment": env})
    return {"id": cred_id, "application_id": application_id, "environment": env, "token": token,
            "note": "Store this token in the relay's secret store now; it is not shown again."}


@router.get("/applications/{application_id}/relay-credentials")
def list_relay_credentials(application_id: str, caller: Caller = CustomerCaller):
    with tenant_session(caller.workspace_id) as s:
        svc.get_application(s, application_id)
        tasks = [relay.to_json(t) for t in s.scalars(select(RelayTask).where(RelayTask.application_id == application_id)
                                                      .order_by(RelayTask.created_at.desc()).limit(20))]
    with platform_session() as p:
        creds = [{"id": c.id, "environment": c.environment, "revoked": c.revoked}
                 for c in p.scalars(select(ServiceCredential).where(ServiceCredential.kind == "relay", ServiceCredential.workspace_id == caller.workspace_id,
                                                                     ServiceCredential.application_id == application_id))]
    return {"credentials": creds, "recent_tasks": tasks}


@router.post("/applications/{application_id}/relay-credentials/{credential_id}/revoke")
def revoke_relay_credential(application_id: str, credential_id: str, caller: Caller = CustomerCaller):
    caller.require_role("owner")
    with platform_session() as p:
        cred = p.get(ServiceCredential, credential_id)
        if cred is None or cred.kind != "relay" or cred.workspace_id != caller.workspace_id or cred.application_id != application_id:
            raise api_error(404, "not_found", "relay credential not found")
        cred.revoked = True
    with tenant_session(caller.workspace_id) as s:
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="relay.credential.revoke",
                    target=credential_id)
    return {"id": credential_id, "revoked": True}


# ---------------- Relay protocol (relay credential only) ----------------

@router.post("/integration/relay/claim")
def claim(svc_: Service = Depends(relay_service)):
    with tenant_session(svc_.workspace_id) as s:
        task = relay.claim(s, application_id=svc_.application_id, credential_id=svc_.credential_id)
    if task is None:
        return Response(status_code=204)
    return task


class ResultIn(BaseModel):
    nonce: str = Field(min_length=10, max_length=100)
    result: dict


@router.post("/integration/relay/tasks/{task_id}/result")
def submit_result(task_id: str, body: ResultIn, svc_: Service = Depends(relay_service)):
    with tenant_session(svc_.workspace_id) as s:
        try:
            task = relay.complete(s, task_id=task_id, application_id=svc_.application_id, credential_id=svc_.credential_id,
                                  nonce=body.nonce, result=body.result)
        except relay.RelayError as exc:
            if exc.code == "expired":
                s.commit()  # keep the expired state
            raise api_error({"not_found": 404, "bad_nonce": 403, "not_claimed": 409, "expired": 410}.get(exc.code, 422), exc.code, exc.detail)
        applied = None
        if task.kind == "verify":
            conn = s.get(Connection, task.ref_id)
            if conn is not None and conn.status == "pending_relay":
                applied = connections.apply_relay_verification(s, conn, body.result, try_for_application(s, conn.application_id))["status"]
        cases.audit(s, workspace_id=svc_.workspace_id, actor=f"relay:{svc_.credential_id}", actor_kind="service", action=f"relay.{task.kind}.result",
                    target=task.id, detail={"ref": task.ref_id, "verification": applied})
        return {"task_id": task.id, "status": task.status, "verification": applied}
