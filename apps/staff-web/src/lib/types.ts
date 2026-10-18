// Response shapes of the AssureOps staff API (apps/api/assureops_api/routes_staff.py and services.py).
// Nested readiness, finding, assessment, release and change shapes match the customer portal's types.

import type { Evidence } from "@assureops/ui/evidence-drawer";

export type { Evidence };

export type Severity = "critical" | "high" | "medium" | "low";
export type ControlResult = "supported" | "failed" | "unverified" | "review_required" | "unassessed";
export type EvidenceValidity = "current" | "stale" | "unavailable" | "not_collected";
export type Duty = "analyst" | "reviewer";

export type Me = { user: string; display_name: string; roles: string[] };

// ---------------- Readiness (services.overview / reducer.readiness) ----------------

export type TestState = {
  test_id: string;
  control: string;
  name: string;
  severity: Severity;
  requires_review: boolean;
  depends_on: string[];
  result: ControlResult;
  validity: EvidenceValidity;
  reused: boolean;
  run_id?: string;
  outcome?: "passed" | "failed" | "error";
  release?: string;
  at?: number;
  trials?: number;
  passed_trials?: number;
  review?: { reviewer: string; decision: string } | null;
};

export type ControlState = {
  id: string;
  name: string;
  family: string;
  weight: number;
  result: ControlResult;
  evidence_validity: EvidenceValidity;
  failure_severity: Severity | null;
  runtime_violation: boolean;
  passed: number;
  total: number;
};

export type Scores = {
  evidence_support_pct: number | null;
  evidence_coverage_pct: number | null;
  controls_supported: number;
  controls_covered: number;
  controls_total: number;
};

export type Gate = { status: "blocked" | "incomplete" | "ready"; reason: string; blocking: string[]; warnings: string[]; incomplete: string[] };

export type Readiness = {
  release: { id: string; version: string; collection_status: string };
  profile: { version: string; gate_policy: string };
  tests: TestState[];
  controls: ControlState[];
  scores: Scores;
  counts: { tests_total: number; tests_current_passing: number; retest_needed: number; critical_open: number; open_findings: number };
  gate: Gate;
  computed_at: number;
};

export type Change = {
  component: string;
  type: string;
  change: "added" | "removed" | "changed";
  impact: Severity | "none" | "unknown";
  label: string;
  affected_tests: string[];
  affected_controls: string[];
  before: string | null;
  after: string | null;
};

export type ChangeSet = {
  id?: string;
  plan_id?: string;
  created_at?: number;
  created_by?: string;
  base: string | null;
  target: string;
  changes: Change[];
  unmapped: string[];
  partial_collection: boolean;
  conservative_fallback: boolean;
  retest: { test_id: string; control: string; reasons: string[] }[];
  reusable: string[];
  plan?: string[];
  edge_revision: string;
};

export type Finding = {
  id: string;
  control: string;
  control_name: string;
  test_id: string | null;
  source: "test" | "runtime";
  severity: Severity;
  title: string;
  description: string;
  state: "open" | "under_review" | "resolved" | "reopened";
  revision: number;
  first_release: string | null;
  last_release: string | null;
  evidence_refs: { run_id?: string; event_revision?: number; release: string; outcome?: string }[];
  resolution: Record<string, unknown> | null;
  created_at: number;
  updated_at: number;
  reviews?: { reviewer: string; reviewer_kind: string; decision: string; note: string; at: number }[];
};

export type AssessmentJob = {
  id: string;
  release: string | null;
  scope: "full" | "retest";
  status: "queued" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled";
  plan_id: string;
  profile_version: string;
  tests: string[];
  case_id: string | null;
  requested_by: string;
  steps: { test_id: string; status: string; attempt: number; error: string | null; run_id: string | null }[];
  summary: { results?: { test_id: string; status: string; run_id: string | null }[]; gate?: string; scores?: Scores } | null;
  error: string | null;
  cancel_requested: boolean;
  created_at: number;
  finished_at: number | null;
};

export type ReleaseInfo = {
  id: string;
  version: string;
  manifest_hash: string;
  components: Record<string, { type: string; fingerprint: string }>;
  policy_versions: Record<string, string>;
  integration: { adapter?: string; mode?: string; mcp_protocol_version?: string };
  collection_status: "complete" | "partial";
  collection_gaps: string[];
  created_at: number;
};

export type Coverage = {
  status: "current" | "degraded" | "unknown" | "not_connected";
  current: number;
  expected: number;
  sources: { source_id: string; kind: string; status: string; last_seen: number | null; release: string | null; missing_sequences: number }[];
};

export type Health = { status: "up" | "error" | "unreachable"; latency_ms: number | null; checked_at: number; window: string };

export type Overview = {
  application: { id: string; name: string; description: string; environment: string; mode: string };
  runtime: Coverage;
  health: Health;
  release: (ReleaseInfo & { previous: string | null }) | null;
  readiness?: Readiness;
  change?: ChangeSet | null;
  findings?: Finding[];
  trend?: { release: string; evidence_support: number; evidence_coverage: number; at: number }[];
  assessment?: { running: AssessmentJob | null; last: AssessmentJob | null };
  case?: { id: string; title: string; state: string } | null;
  publication?: { report_id: string; release: string; at: number } | null;
};

// ---------------- Staff queues ----------------

export type Assignee = { user: string | null; duty: Duty };

export type QueueItem = {
  case_id: string;
  workspace: string;
  application: string;
  title: string;
  state: string;
  priority: string;
  blockers: number;
  updated_at: number;
  queue_age_hours: number;
  your_duty: Duty | null;
  assignees: Assignee[];
};

export type ReviewQueueItem = {
  case_id: string;
  case_title: string;
  report_id: string;
  release: string;
  drafted_by: string;
  revision: number;
  gate: Gate["status"];
  at: number;
};

// ---------------- Case workspace ----------------

export type CaseMessage = { id: string; author: string; author_kind: string; visibility: "internal" | "customer"; body: string; at: number };

export type EvidenceRequest = {
  id: string;
  requested_by: string;
  body: string;
  state: string;
  response: string | null;
  responded_by: string | null;
  at: number;
};

export type ReportSummary = { id: string; state: string; release: string; sha256: string; drafted_by: string; revision: number; at: number };

export type CaseDetail = {
  id: string;
  application_id: string;
  title: string;
  scope_note: string;
  state: string;
  priority: string;
  revision: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  messages: CaseMessage[];
  evidence_requests: EvidenceRequest[];
  reports: ReportSummary[];
  application: {
    id: string;
    name: string;
    environment: string;
    mode: string;
    purpose: string;
    authorized_scope: Record<string, unknown>;
  };
  overview: Overview;
  findings: Finding[];
  assessments: AssessmentJob[];
  assignees: Assignee[];
  your_duty: Duty;
};

// ---------------- Investigation ----------------

export type ProfileTest = {
  id: string;
  control: string;
  severity: Severity;
  trials: number;
  name: string;
  requires_review?: boolean;
  mandatory?: boolean;
};

export type CoverageContract = {
  adapter_id?: string;
  adapter_version?: string;
  revision?: number;
  reviewer?: string;
  reviewed_against?: string;
  supported_component_types?: string[];
  collection_method?: Record<string, string>;
  mandatory_components?: Record<string, string[]>;
  dependency_edges?: Record<string, string[]>;
  volatile_sources?: unknown[];
  freshness_policy?: { default_days?: number };
  runtime_sources?: { source_id: string; kind: string; environment: string }[];
  unknowns?: unknown[];
  exclusions?: unknown[];
};

export type DependencyEdge = {
  id: string;
  test_id: string;
  component_id: string;
  status: "accepted" | "proposed" | "rejected";
  source: string;
  rationale: string | null;
  reviewer: string | null;
  revision: number;
  updated_at: number;
};

export type Investigation = {
  case: { id: string; title: string; state: string };
  release: ReleaseInfo | null;
  coverage_contract: CoverageContract;
  edges: DependencyEdge[];
  unmapped_components: string[];
  change: ChangeSet | null;
  tests: ProfileTest[];
  connection?: import("@/components/case/ProfilePanel").ConnectionSummary;
  your_duty: Duty;
};

// ---------------- Reports ----------------

export type ReportSnapshot = {
  application: { id: string; name: string; environment: string; mode: string };
  case: { id: string; title: string; scope_note: string };
  release: { version: string; manifest_hash: string; collection_status: string };
  profile: string;
  readiness: Readiness;
  findings: Finding[];
  evidence: Evidence[];
  scope_note: string;
  generated_at: number;
};

export type ReportDetail = {
  id: string;
  state: string;
  sha256: string;
  integrity: "verified" | "tampered";
  revision: number;
  drafted_by: string;
  snapshot: ReportSnapshot;
  created_at: number;
  publication: { state: string; published_by: string; at: number } | null;
  current_status: { release: string; gate: Gate; scores: Scores } | null;
  decisions: { reviewer: string; decision: string; reason: string; at: number }[];
};

// ---------------- Incidents, operations, governance ----------------

export type Incident = {
  id: string;
  case_id: string;
  case_title: string;
  control: string;
  severity: Severity;
  title: string;
  state: "open" | "closed";
  revision: number;
  cohort: string;
  closure: { by: string; reviewer: string; note: string; release: string; run_ids: (string | null)[]; at: number } | null;
  created_at: number;
  your_duty: Duty;
};

export type Operations = {
  outbox: { pending: number; oldest_age_seconds: number };
  steps: { pending: number; running: number; expired_leases: number; failed: number };
  jobs: { queued: number; running: number; failed_last_day: number };
  ingestion: { events_last_5_minutes: number };
  inference: { routes_enabled: number; note: string };
  runner: { isolation: string; note: string };
};

export type Governance = {
  profile: {
    version: string;
    digest: string;
    controls: Record<string, { name: string; family: string; weight: number }>;
    gate_policy: { version: string; blocking_severities: string[]; incomplete_when: string[] };
    tests: ProfileTest[];
    requirements: Record<string, unknown>;
  };
  model_routes: { phase: string; id?: string; model: string; parameters?: string; enabled: boolean; qualification: unknown; optional?: boolean;
    status?: string; route?: { provider: string | null; model: string | null; external: boolean } }[];
  qualification_records: unknown[];
  staff_permissions: { user: string; name: string; roles: string[] }[];
  identity: { provider: string; staff_mfa: string };
};
