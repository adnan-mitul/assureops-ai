"""Prometheus metrics: platform counts only, never customer content. Loopback or a `metrics` service credential."""

import time

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import AiResult, Assessment, Incident, JobStep, ModelCall, Outbox, RuntimeEvent, ServiceCredential, Workspace

from .auth import api_error, token_hash

router = APIRouter(tags=["metrics"])


def _allowed(request: Request, authorization: str | None) -> bool:
    if request.client and request.client.host in ("127.0.0.1", "::1", "localhost"):
        return True
    if authorization and authorization.startswith("Bearer "):
        with platform_session() as s:
            cred = s.scalars(select(ServiceCredential).where(ServiceCredential.token_hash == token_hash(authorization[7:]),
                                                             ServiceCredential.kind == "metrics", ServiceCredential.revoked.is_(False))).first()
            return cred is not None
    return False


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request, authorization: str | None = Header(default=None)):
    if not _allowed(request, authorization):
        raise api_error(403, "forbidden", "metrics are available on loopback or with a metrics credential")
    now = time.time()
    lines: list[str] = []

    def gauge(name: str, help_: str, values: dict[tuple, float]):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        for labels, value in values.items():
            label = ",".join(f'{k}="{v}"' for k, v in labels) if labels else ""
            lines.append(f"{name}{{{label}}} {value}" if label else f"{name} {value}")

    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
        pending = s.scalar(select(func.count()).select_from(Outbox).where(Outbox.dispatched_at.is_(None))) or 0
        oldest = s.scalar(select(func.min(Outbox.created_at)).where(Outbox.dispatched_at.is_(None)))
    steps, jobs, ai, calls, incidents = {}, {}, {}, {}, {}
    events_5m = 0
    expired = 0
    for ws in workspaces:
        with tenant_session(ws) as s:
            for status, n in s.execute(select(JobStep.status, func.count()).group_by(JobStep.status)):
                steps[(("status", status),)] = steps.get((("status", status),), 0) + n
            expired += s.scalar(select(func.count()).select_from(JobStep).where(JobStep.status == "running", JobStep.lease_expires_at < now)) or 0
            for status, n in s.execute(select(Assessment.status, func.count()).group_by(Assessment.status)):
                jobs[(("status", status),)] = jobs.get((("status", status),), 0) + n
            for phase, status, n in s.execute(select(AiResult.phase, AiResult.status, func.count()).group_by(AiResult.phase, AiResult.status)):
                key = (("phase", phase), ("status", status))
                ai[key] = ai.get(key, 0) + n
            for provider, status, n in s.execute(select(ModelCall.provider, ModelCall.status, func.count()).group_by(ModelCall.provider, ModelCall.status)):
                key = (("provider", provider), ("status", status))
                calls[key] = calls.get(key, 0) + n
            for state, n in s.execute(select(Incident.state, func.count()).group_by(Incident.state)):
                incidents[(("state", state),)] = incidents.get((("state", state),), 0) + n
            events_5m += s.scalar(select(func.count()).select_from(RuntimeEvent).where(RuntimeEvent.received_at > now - 300)) or 0
    gauge("assureops_outbox_pending", "Undispatched outbox intents", {(): pending})
    gauge("assureops_outbox_oldest_age_seconds", "Age of the oldest undispatched intent", {(): round(now - oldest) if oldest else 0})
    gauge("assureops_job_steps", "Assessment steps by status", steps)
    gauge("assureops_job_steps_expired_leases", "Running steps whose lease expired", {(): expired})
    gauge("assureops_assessments", "Assessments by status", jobs)
    gauge("assureops_ai_results", "AI phase jobs by phase and status", ai)
    gauge("assureops_model_calls", "Model calls by provider and status", calls)
    gauge("assureops_incidents", "Runtime incidents by state", incidents)
    gauge("assureops_runtime_events_last_5m", "Runtime events ingested in the last five minutes", {(): events_5m})
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
