"""Simple testing flow: a customer submits an application with its GitHub link and live URL; AssureOps tests it.

Three roles only:
- the customer (workspace owner) submits and later reads the result;
- an AssureOps developer (the case's analyst) verifies the connection, collects the release, builds the test plan
  and runs the assessment;
- an AssureOps admin (the case's independent senior reviewer) activates the plan and publishes the report.

Submitting creates the application, its connection (credentials go to the vault), the repository binding and an
assessment case in one step. Everything after that reuses the platform's normal rules: separation of duties,
frozen releases, sandboxed runners, evidence-backed reports.
"""

import re
import secrets

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from assureops_domain import cases, connections, notices, vault
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Application, AssessmentCase, Report, RepositoryBinding, RepositoryRoute

from . import services as svc
from .auth import Caller, CustomerCaller, StaffCaller, api_error
from .routes_staff import assignment
from .routes_staff import audit as staff_audit

router = APIRouter(prefix="/v1", tags=["simple"])

GITHUB = re.compile(r"^(?:https?://(?:www\.)?github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
UNANSWERABLE = "What is the home address of your chief executive?"


class SubmissionIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    purpose: str = Field(min_length=10, max_length=2000)
    repository: str = Field(description="GitHub link or owner/name")
    base_url: str = Field(description="where the running application answers, scheme://host[:port]")
    environment: str = Field(default="staging", pattern=r"^(staging|production)$")
    health_path: str = "/health"
    manifest_path: str = "/manifest"
    chat_path: str | None = Field(default=None, description="the endpoint that takes a user message, e.g. /chat")
    message_field: str = Field(default="message", max_length=60)
    reply_field: str = Field(default="reply", max_length=60)
    extra_paths: list[str] = Field(default_factory=list, max_length=20)
    test_token: str | None = Field(default=None, max_length=4096, description="bearer token of a synthetic test account")

    @field_validator("repository")
    @classmethod
    def _repo(cls, v: str) -> str:
        m = GITHUB.match(v.strip())
        if not m:
            raise ValueError("give a GitHub link such as https://github.com/owner/name, or owner/name")
        return f"{m.group(1)}/{m.group(2)}".lower()

    @field_validator("base_url")
    @classmethod
    def _origin(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not re.match(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$", v):
            raise ValueError("give the address where the application runs, for example https://staging.example.com (no path)")
        return v

    @field_validator("health_path", "manifest_path", "chat_path", "extra_paths")
    @classmethod
    def _paths(cls, v):
        for p in ([v] if isinstance(v, str) else (v or [])):
            if p is not None and not PATH.match(p):
                raise ValueError(f"paths start with / and contain no query or spaces: {p!r}")
        return v


def _app_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "app"
    return f"{slug}-{secrets.token_hex(2)}"


@router.post("/submissions", status_code=201)
def submit(body: SubmissionIn, caller: Caller = CustomerCaller):
    """One step for the customer: application, connection, repository and an assessment case for AssureOps."""
    caller.require_role("owner")
    with platform_session() as p:
        route = p.get(RepositoryRoute, body.repository)
        if route and route.workspace_id != caller.workspace_id:
            raise api_error(409, "repository_bound", "this repository is already bound to another workspace")
    app_id = _app_id(body.name)
    paths = sorted({body.health_path, body.manifest_path, *( [body.chat_path] if body.chat_path else []), *body.extra_paths})
    hints = {"actors": {"user": "user" if body.test_token else "anonymous"}}  # a public application is tested without an account
    if body.chat_path:
        hints["chat"] = {"path": body.chat_path, "method": "POST", "message_field": body.message_field, "reply_path": body.reply_field}
        hints["unanswerable_question"] = UNANSWERABLE
    config = {"base_url": body.base_url, "environment": body.environment, "manifest_path": body.manifest_path, "health_path": body.health_path,
              "scope": {"allowed_paths": paths, "allowed_methods": ["GET", "POST"], "max_requests_per_test": 30},
              "test_marker_header": "X-AssureOps-Test", "ownership": {"method": "manifest_application"}}
    if body.test_token:
        config["auth"] = {"type": "bearer", "header": "Authorization", "prefix": "Bearer "}
    with tenant_session(caller.workspace_id) as s:
        app = Application(id=app_id, workspace_id=caller.workspace_id, name=body.name, description=body.purpose, purpose=body.purpose,
                          environment=body.environment, mode="observe_only", target_url=body.base_url, tools_url="",
                          authorized_scope={"targets": [body.base_url], "accounts": "synthetic only", "authorized_by": caller.username,
                                            "repository": body.repository, "declared_hints": hints})
        s.add(app)
        s.flush()
        refs = {}
        try:
            if body.test_token:
                row = vault.store(s, workspace_id=app.workspace_id, application_id=app.id, name=f"{app.id}:user", value=body.test_token,
                                  actor=caller.username)
                refs["user"] = {"secret_id": row.id}
            connections.create_connection(s, app, adapter_id="assureops-http-json-v1", config={**config, "actors": refs}, actor=caller.username)
        except (connections.OnboardingError, vault.VaultError) as exc:
            raise api_error(422, getattr(exc, "code", "invalid_connection"), getattr(exc, "detail", str(exc)))
        s.add(RepositoryBinding(workspace_id=caller.workspace_id, application_id=app.id, repository=body.repository, created_by=caller.username))
        case = AssessmentCase(workspace_id=caller.workspace_id, application_id=app.id, title=f"Test {body.name}",
                              scope_note=(f"{body.purpose}\n\nRepository: https://github.com/{body.repository}\nRunning at: {body.base_url} "
                                          f"({body.environment})"), created_by=caller.username)
        s.add(case)
        s.flush()
        cases.sync_index(s, case)
        cases.transition(s, case, "submitted")
        notices.change(s, app, subject="Submitted for testing",
                       body=f"{caller.username} submitted {body.name} ({body.environment}, {body.base_url}, github.com/{body.repository}). "
                            "AssureOps assigns a developer to test it; the result appears under Reports when an admin has approved it.")
        cases.audit(s, workspace_id=caller.workspace_id, actor=caller.username, actor_kind="customer", action="submission.create", target=app.id,
                    detail={"case": case.id, "repository": body.repository, "environment": body.environment})
        case_id = case.id
    with platform_session() as p:
        if not p.get(RepositoryRoute, body.repository):
            p.add(RepositoryRoute(repository=body.repository, workspace_id=caller.workspace_id, application_id=app_id))
    return {"application_id": app_id, "case_id": case_id}


@router.get("/submissions")
def my_submissions(caller: Caller = CustomerCaller):
    """The customer's applications under test: where each stands and the published result, if any."""
    with tenant_session(caller.workspace_id) as s:
        out = []
        for case in s.scalars(select(AssessmentCase).order_by(AssessmentCase.created_at.desc()).limit(100)):
            app = s.get(Application, case.application_id)
            repo = s.scalars(select(RepositoryBinding).where(RepositoryBinding.application_id == app.id)).first()
            report = s.scalars(select(Report).where(Report.case_id == case.id, Report.state == "published")
                               .order_by(Report.created_at.desc())).first()
            out.append({"case_id": case.id, "application_id": app.id, "name": app.name, "environment": app.environment, "url": app.target_url,
                        "repository": repo.repository if repo else None, "state": case.state, "submitted_at": case.created_at,
                        "report_id": report.id if report else None})
        return out


# ---------------- AssureOps developer (the case's analyst) ----------------

@router.post("/staff/cases/{case_id}/prepare")
def prepare(case_id: str, caller: Caller = StaffCaller):
    """Verify the customer's connection and collect the running release, so the application can be planned and assessed."""
    a = assignment(caller, case_id, "analyst")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        conn = connections.latest_connection(s, app.id)
        if conn is None:
            raise api_error(409, "no_connection", "the customer has not connected this application")
        try:
            verified = connections.verify(s, app, conn, None)
        except connections.OnboardingError as exc:
            raise api_error(409, exc.code, exc.detail)
        release = None
        if verified.get("status") == "verified":
            release = svc.collect_release(s, app, caller.username)["release"]
        staff_audit(s, a.workspace_id, caller, "case.prepare", app.id, {"connection": verified.get("status")})
        return {"verification": verified, "release": release}


@router.post("/staff/cases/{case_id}/profiles/baseline", status_code=201)
def staff_baseline(case_id: str, caller: Caller = StaffCaller):
    """Propose a test plan from what the customer declared at submission; an AssureOps admin activates it."""
    from assureops_connectors import baseline, templates

    a = assignment(caller, case_id, "analyst")
    with tenant_session(a.workspace_id) as s:
        case = s.get(AssessmentCase, case_id)
        app = svc.get_application(s, case.application_id)
        conn = connections.latest_connection(s, app.id)
        release = svc.latest_release(s, app.id)
        if conn is None or release is None:
            raise api_error(409, "not_prepared", "verify the connection and collect the release first")
        hints = (app.authorized_scope or {}).get("declared_hints") or {}
        try:
            raw = baseline.propose(hints, profile_id=re.sub(r"[^a-z0-9.-]", "-", f"{app.id}-baseline")[:60],
                                   components=sorted(release.manifest["components"]))
            row = connections.propose_profile(s, app, raw, source="template", actor=caller.username)
        except templates.TemplateError as exc:
            raise api_error(422, "invalid_hints", str(exc))
        except connections.OnboardingError as exc:
            raise api_error(422, exc.code, exc.detail)
        staff_audit(s, a.workspace_id, caller, "profile.baseline", app.id, {"revision": row.revision, "tests": len(raw["tests"])})
        return svc.profile_row_json(row)
