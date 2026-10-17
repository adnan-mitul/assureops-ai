"""Persistent model.

Tenant tables carry `workspace_id`, use workspace-consistent composite foreign
keys and are protected by row-level security (see the RLS migration). Platform
tables hold identities, credentials, assignment metadata and the outbox; they
never hold customer evidence.
"""

import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now() -> float:
    return time.time()


def tenant_keys(*refs: tuple[str, str]):
    """Unique (workspace_id, id) plus composite FKs so references cannot cross workspaces."""
    args = [UniqueConstraint("workspace_id", "id")]
    for column, target in refs:
        args.append(ForeignKeyConstraint(["workspace_id", column], [f"{target}.workspace_id", f"{target}.id"]))
    return tuple(args)


# ---------------- Platform tables (no tenant content) ----------------

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("usr"))
    username: Mapped[str] = mapped_column(String, unique=True)  # OIDC preferred_username
    display_name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # customer | staff
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    """Customer-company role in one workspace; the token never carries roles."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("mem"))
    workspace_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)  # owner | developer | reviewer | viewer
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class StaffRole(Base):
    __tablename__ = "staff_roles"
    __table_args__ = (UniqueConstraint("user_id", "role"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("srl"))
    user_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)  # analyst | senior_reviewer | case_manager | operator
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceCredential(Base):
    """Scoped machine credentials (runner, gateway, tool server). Only hashes are stored."""

    __tablename__ = "service_credentials"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("svc"))
    kind: Mapped[str] = mapped_column(String)  # runner | gateway | tool_server
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class EventSource(Base):
    """Authenticated runtime event source bound to one application and environment."""

    __tablename__ = "event_sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # source_id, e.g. refund-agent-1
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class CaseIndex(Base):
    """Operational metadata for staff queues. Raw evidence stays behind case-scoped grants."""

    __tablename__ = "case_index"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    workspace_name: Mapped[str] = mapped_column(String)
    application_name: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)
    blockers: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("asg"))
    case_id: Mapped[str] = mapped_column(String, index=True)
    workspace_id: Mapped[str] = mapped_column(String)
    staff_user_id: Mapped[str] = mapped_column(String)
    duty: Mapped[str] = mapped_column(String)  # analyst | reviewer
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by: Mapped[str] = mapped_column(String)
    granted_at: Mapped[float] = mapped_column(Float, default=now)
    revoked_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Outbox(Base):
    """Dispatch intents committed with the domain transition that created them."""

    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # run_step | finalize_assessment
    ref_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    dispatched_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (Index("ix_outbox_pending", "dispatched_at"),)


# ---------------- Tenant tables (row-level security) ----------------

class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    environment: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)  # observe_only | enforce_supported_actions
    target_url: Mapped[str] = mapped_column(String)
    tools_url: Mapped[str] = mapped_column(String)
    authorized_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class CoverageContract(Base):
    __tablename__ = "coverage_contracts"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("cov"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer)
    contract: Mapped[dict] = mapped_column(JSON)
    reviewer: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class DependencyEdge(Base):
    __tablename__ = "dependency_edges"
    __table_args__ = tenant_keys(("application_id", "applications")) + (UniqueConstraint("workspace_id", "application_id", "test_id", "component_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("edg"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    test_id: Mapped[str] = mapped_column(String)
    component_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # proposed | accepted | rejected
    source: Mapped[str] = mapped_column(String)  # coverage_contract | analyst | rule | ai
    rationale: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Release(Base):
    """Immutable record of a collected manifest."""

    __tablename__ = "releases"
    __table_args__ = tenant_keys(("application_id", "applications")) + (UniqueConstraint("workspace_id", "application_id", "manifest_hash"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rel"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSON)
    manifest_hash: Mapped[str] = mapped_column(String)
    collection_gaps: Mapped[list] = mapped_column(JSON, default=list)
    collection_status: Mapped[str] = mapped_column(String)  # complete | partial
    collected_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class ChangeSet(Base):
    __tablename__ = "change_sets"
    __table_args__ = tenant_keys(("application_id", "applications"), ("target_release_id", "releases"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("chg"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    base_release_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_release_id: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)
    plan_id: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = tenant_keys(("application_id", "applications"), ("release_id", "releases")) + (
        UniqueConstraint("workspace_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("asm"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    release_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String)  # full | retest
    plan_id: Mapped[str] = mapped_column(String)
    plan: Mapped[dict] = mapped_column(JSON)
    profile_version: Mapped[str] = mapped_column(String)
    edge_revision: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|running|awaiting_review|completed|failed|cancelled
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class JobStep(Base):
    """One logical step with lease ownership and a monotonically increasing fencing token."""

    __tablename__ = "job_steps"
    __table_args__ = tenant_keys(("assessment_id", "assessments")) + (UniqueConstraint("workspace_id", "step_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("stp"))
    workspace_id: Mapped[str] = mapped_column(String)
    assessment_id: Mapped[str] = mapped_column(String)
    step_key: Mapped[str] = mapped_column(String)  # assessment_id:test_id
    test_id: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|running|done|failed|cancelled
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    result_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class Artifact(Base):
    """Metadata for content-addressed evidence bytes kept in private storage."""

    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("workspace_id", "id"), UniqueConstraint("workspace_id", "sha256"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("art"))
    workspace_id: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    deleted_at: Mapped[float | None] = mapped_column(Float, nullable=True)  # tombstone
    created_at: Mapped[float] = mapped_column(Float, default=now)


class TestRun(Base):
    __test__ = False  # not a pytest test class
    __tablename__ = "test_runs"
    __table_args__ = tenant_keys(("application_id", "applications"), ("release_id", "releases"), ("assessment_id", "assessments"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("run"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    release_id: Mapped[str] = mapped_column(String)
    assessment_id: Mapped[str] = mapped_column(String)
    step_id: Mapped[str] = mapped_column(String, unique=True)  # one committed result per logical step
    test_id: Mapped[str] = mapped_column(String)
    control_id: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)  # passed | failed | error
    trials: Mapped[int] = mapped_column(Integer)
    passed_trials: Mapped[int] = mapped_column(Integer)
    trial_outcomes: Mapped[list] = mapped_column(JSON)
    dependency_fingerprints: Mapped[dict] = mapped_column(JSON)
    profile_version: Mapped[str] = mapped_column(String)
    artifact_id: Mapped[str] = mapped_column(String)
    expected: Mapped[str] = mapped_column(Text)
    observation_source: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class EvidenceReview(Base):
    """Reviewer decision on one immutable test run (e.g. semantic results before a qualified evaluator exists)."""

    __tablename__ = "evidence_reviews"
    __table_args__ = tenant_keys(("run_id", "test_runs"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("evr"))
    workspace_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)  # accept | reject
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("fnd"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    control_id: Mapped[str] = mapped_column(String)
    test_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)  # test | runtime
    severity: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default="open")  # open | under_review | resolved | reopened
    revision: Mapped[int] = mapped_column(Integer, default=1)
    first_release: Mapped[str | None] = mapped_column(String, nullable=True)
    last_release: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    resolution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remediation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class FindingReview(Base):
    """Revision-checked reviewer decision with its evidence references."""

    __tablename__ = "finding_reviews"
    __table_args__ = tenant_keys(("finding_id", "findings"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("frv"))
    workspace_id: Mapped[str] = mapped_column(String)
    finding_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    reviewer_kind: Mapped[str] = mapped_column(String)  # customer | staff
    decision: Mapped[str] = mapped_column(String)  # confirm | dispute | remediation_submitted | erroneous
    note: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    finding_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Approval(Base):
    """One approval authorizes one logical action, bound to its exact context and payload."""

    __tablename__ = "approvals"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("apr"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)
    release: Mapped[str] = mapped_column(String)
    tool: Mapped[str] = mapped_column(String)
    tool_schema_hash: Mapped[str] = mapped_column(String)
    payload_hash: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    permission_policy_version: Mapped[str] = mapped_column(String)
    approval_policy_version: Mapped[str] = mapped_column(String)
    requester: Mapped[str] = mapped_column(String)
    approver: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="granted")  # granted|reserved|consumed|expired|revoked
    action_id: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class LogicalAction(Base):
    __tablename__ = "logical_actions"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True)  # server-issued action_id / external idempotency key
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    approval_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str] = mapped_column(String)
    payload_hash: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)  # prepared|reserved|dispatching|succeeded|failed_definitive|outcome_unknown
    # "assessment" only when the request carried the ID of a step AssureOps itself is running; otherwise "live".
    origin: Mapped[str] = mapped_column(String, default="live", server_default="live")
    release: Mapped[str] = mapped_column(String, default="unknown", server_default="unknown")  # cohort that requested the action
    claim_revision: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"
    __table_args__ = (UniqueConstraint("workspace_id", "event_id"),)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # database ingestion revision
    workspace_id: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    epoch: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(Integer)
    release: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    classification: Mapped[str] = mapped_column(String)
    trust_origin: Mapped[str] = mapped_column(String)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    body_hash: Mapped[str] = mapped_column(String)
    observed_at: Mapped[float] = mapped_column(Float)
    received_at: Mapped[float] = mapped_column(Float, default=now)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("inc"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    control_id: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="open")  # open | closed
    revision: Mapped[int] = mapped_column(Integer, default=1)
    release: Mapped[str] = mapped_column(String)
    cohort: Mapped[str] = mapped_column(String)
    event_revisions: Mapped[list] = mapped_column(JSON)
    finding_id: Mapped[str] = mapped_column(String)
    closure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class AssessmentCase(Base):
    __tablename__ = "assessment_cases"
    __table_args__ = tenant_keys(("application_id", "applications"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("case"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    scope_note: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default="draft")
    priority: Mapped[str] = mapped_column(String, default="normal")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class EvidenceRequest(Base):
    __tablename__ = "evidence_requests"
    __table_args__ = tenant_keys(("case_id", "assessment_cases"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("req"))
    workspace_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String, default="open")  # open | answered
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    answered_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class CaseMessage(Base):
    __tablename__ = "case_messages"
    __table_args__ = tenant_keys(("case_id", "assessment_cases"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("msg"))
    workspace_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    author: Mapped[str] = mapped_column(String)
    author_kind: Mapped[str] = mapped_column(String)  # customer | staff
    visibility: Mapped[str] = mapped_column(String)  # customer | internal
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Report(Base):
    """Frozen, hashed snapshot. Publication is a separate, reviewed record."""

    __tablename__ = "reports"
    __table_args__ = tenant_keys(("application_id", "applications"), ("case_id", "assessment_cases"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rpt"))
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    release_id: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String)
    drafted_by: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="draft")  # draft | published | returned | superseded | withdrawn
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = tenant_keys(("report_id", "reports"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rvd"))
    workspace_id: Mapped[str] = mapped_column(String)
    report_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)  # publish | return
    reason: Mapped[str] = mapped_column(Text)
    report_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class ReportPublication(Base):
    __tablename__ = "report_publications"
    __table_args__ = tenant_keys(("report_id", "reports"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("pub"))
    workspace_id: Mapped[str] = mapped_column(String)
    report_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    release: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    published_by: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="published")  # published | superseded | withdrawn
    created_at: Mapped[float] = mapped_column(Float, default=now)


class ReadinessPoint(Base):
    __tablename__ = "readiness_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String)
    application_id: Mapped[str] = mapped_column(String)
    assessment_id: Mapped[str] = mapped_column(String)
    release: Mapped[str] = mapped_column(String)
    evidence_support: Mapped[float] = mapped_column(Float)
    evidence_coverage: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    actor_kind: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


TENANT_TABLES = [
    "applications", "coverage_contracts", "dependency_edges", "releases", "change_sets", "assessments", "job_steps",
    "artifacts", "test_runs", "findings", "finding_reviews", "approvals", "logical_actions", "runtime_events",
    "incidents", "assessment_cases", "evidence_requests", "case_messages", "reports", "review_decisions",
    "report_publications", "readiness_points", "audit_events", "evidence_reviews",
]
