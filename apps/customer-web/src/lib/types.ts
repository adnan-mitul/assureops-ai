// Response shapes of the AssureOps customer API (apps/api/assureops_api/routes_customer.py and services.py).

import type { Evidence } from "@assureops/ui/evidence-drawer";

export type Severity = "critical" | "high" | "medium" | "low";

export type TestState = {
  test_id: string;
  control: string;
  name: string;
  severity: Severity;
  requires_review: boolean;
  depends_on: string[];
  result: "supported" | "failed" | "unverified" | "review_required";
  validity: "current" | "stale" | "unavailable";
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
  result: "supported" | "failed" | "unverified" | "review_required" | "unassessed";
  evidence_validity: "current" | "stale" | "unavailable";
  failure_severity: Severity | null;
  runtime_violation: boolean;
  passed: number;
  total: number;
};

export type Readiness = {
  release: { id: string; version: string; collection_status: string };
  profile: { version: string; gate_policy: string };
  tests: TestState[];
  controls: ControlState[];
  scores: {
    evidence_support_pct: number | null;
    evidence_coverage_pct: number | null;
    controls_supported: number;
    controls_covered: number;
    controls_total: number;
    controls_assessed?: number;
    controls_unassessed?: number;
  };
  counts: { tests_total: number; tests_current_passing: number; retest_needed: number; critical_open: number; open_findings: number };
  gate: { status: "blocked" | "incomplete" | "ready"; reason: string; blocking: string[]; warnings: string[]; incomplete: string[];
    unassessed?: string[]; scope_limited?: boolean };
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
  release: string;
  scope: "full" | "retest";
  status: "queued" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled";
  plan_id: string;
  profile_version: string;
  tests: string[];
  case_id: string | null;
  requested_by: string;
  steps: { test_id: string; status: string; attempt: number; error: string | null; run_id: string | null }[];
  summary: { results?: { test_id: string; status: string; run_id: string | null }[]; gate?: string; scores?: Readiness["scores"] };
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
  sources: { source_id: string; kind: string; status: string; last_seen: number | null; release: string | null; missing_sequences: number; epoch?: string | number }[];
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
  onboarding?: { steps: { id: string; label: string; done: boolean }[]; complete: boolean };
};

export type ApplicationSummary = {
  id: string;
  name: string;
  description: string;
  environment: string;
  mode: string;
  release: string | null;
  gate: Readiness["gate"] | null;
  scores: Readiness["scores"] | null;
  profile: string | null;
  onboarding: { steps: { id: string; label: string; done: boolean }[]; complete: boolean;
    connection: { status: string; revision: number; adapter_id: string; gaps: string[] } | null;
    profile: { version: string; assessed_controls: string[]; unassessed_controls: string[]; tests: number } | null } | null;
};

export type Me = { user: string; display_name: string; workspace_id: string; role: string; memberships: Record<string, string> };

export type { Evidence };

export type ReleaseSubmitResult = { release: ReleaseInfo; created: boolean; gaps: string[]; change_id?: string };

export type AssessmentCreated = { id: string; status: AssessmentJob["status"]; plan_id: string; tests: string[] };

export type FindingResolution =
  | { by: "retest"; run_id: string; release: string; at: number }
  | { by: "reviewer"; reviewer: string; note: string; release: string; run_ids: string[]; at: number };

export type FindingDetail = Omit<Finding, "resolution"> & {
  resolution: FindingResolution | null;
  reviews: NonNullable<Finding["reviews"]>;
  evidence: Evidence[];
};

export type Incident = {
  id: string;
  control: string;
  severity: Severity;
  title: string;
  state: "open" | "closed";
  revision: number;
  release: string;
  cohort: string;
  finding_id: string;
  closure: { by: string; reviewer: string; note: string; release: string; run_ids: string[]; at: number } | null;
  created_at: number;
};

export type RuntimeEvent = {
  revision: number;
  source_id: string;
  seq: number;
  epoch: string | number;
  release: string;
  type: string;
  classification: "violation" | "enforcement_blocked" | "review_required" | "assessment_traffic" | "observed";
  trust_origin: string;
  payload: Record<string, unknown>;
  received_at: number;
};

export type Monitoring = {
  coverage: Coverage;
  incidents: Incident[];
  events: RuntimeEvent[];
  health: Health;
  mode: string;
};

export type DemoChatReply = {
  reply: string;
  release: string;
  actions: { tool: string; args: Record<string, unknown>; outcome: string; reason?: string; detail?: string; result?: Record<string, unknown> }[];
  citations?: unknown[];
  steps?: number;
};

export type ApprovalGrant = { approval_id: string; expires_at: number; bound_to: { release: string; requester: string } };

export type ReportListItem = { report_id: string; release: string; sha256: string; state: "published" | "superseded"; published_by: string; at: number };

export type ReportDetail = {
  id: string;
  state: "published" | "superseded";
  sha256: string;
  integrity: "verified" | "tampered";
  revision: number;
  drafted_by: string;
  created_at: number;
  snapshot: {
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
  publication: { state: string; published_by: string; at: number } | null;
  current_status: { release: string; gate: Readiness["gate"]; scores: Readiness["scores"] } | null;
};

export type CaseState =
  | "draft" | "submitted" | "triage" | "assessment" | "awaiting_customer" | "awaiting_review" | "published" | "monitoring" | "reassessment";

export type AssessmentCase = {
  id: string;
  application_id: string;
  title: string;
  scope_note: string;
  state: CaseState;
  priority: string;
  revision: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  messages: { id: string; author: string; author_kind: string; visibility: string; body: string; at: number }[];
  evidence_requests: { id: string; requested_by: string; body: string; state: string; response: string | null; responded_by: string | null; at: number }[];
  reports: { id: string; state: string; release: string; sha256: string; drafted_by: string; revision: number; at: number }[];
};

export type Settings = {
  workspace: string;
  your_role: string;
  you: string;
  members: { user: string; name: string; role: string }[];
  your_applications: string[];
  applications: { id: string; name: string; mode: string; environment: string; target_url: string; tools_url: string; authorized_scope: Record<string, unknown> }[];
  profile: {
    version: string;
    controls: Record<string, { name: string; family: string; weight: number }>;
    gate_policy: Record<string, unknown>;
    requirements: Record<string, unknown>;
    evidence_freshness_days: number;
  };
  data_policy: { inference: string; external_processing: boolean; training_on_customer_evidence: boolean };
  model_routes: { phase: string; id?: string; model: string; parameters?: string; enabled: boolean; qualification: unknown; optional?: boolean;
    status?: string; route?: { provider: string | null; model: string | null; external: boolean } }[];
  retention: { evidence_days: number; runtime_events_days: number };
};
