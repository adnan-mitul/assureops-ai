import type { Metadata } from "next";
import {
  Activity, ArrowRight, BadgeCheck, Bot, CheckCircle2, Cpu, Database, FileCheck2, GitBranch, Lock, Network, RefreshCw, ShieldAlert,
  ShieldCheck, Terminal, Workflow,
} from "lucide-react";
import Link from "next/link";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AssureOps AI — Live Architecture, Whitepaper & System Docs",
  description: "Live technical documentation, pitch summary, control catalog, AI qualification benchmarks, MCP architecture, and system health for AssureOps AI.",
};

type HealthProbe = {
  ok: boolean;
  label: string;
  checkedAt: string;
};

async function probeApiHealth(): Promise<HealthProbe> {
  const base = (process.env.ASSUREOPS_API_URL || "http://127.0.0.1:8700").replace(/\/$/, "");
  const checkedAt = new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC";
  try {
    const res = await fetch(`${base}/health`, { cache: "no-store", signal: AbortSignal.timeout(1200) });
    if (res.ok) {
      return { ok: true, label: "API Online (200 OK)", checkedAt };
    }
    return { ok: false, label: `API Degraded (HTTP ${res.status})`, checkedAt };
  } catch {
    return { ok: false, label: "API Unreachable (Preview Mode)", checkedAt };
  }
}

const VALUE_PILLARS = [
  {
    icon: RefreshCw,
    title: "Selective Dependency-Driven Retesting",
    body: "Release manifests freeze (version, component hash). When code changes, reviewed dependency maps invalidate only the affected evidence—cutting redundant retests while forcing conservative re-runs on unmapped changes.",
  },
  {
    icon: ShieldCheck,
    title: "Evidence Boundaries, Not Fake Safety Scores",
    body: "AssureOps measures deterministic evidence support and coverage across C01–C10. Uncovered controls stay visibly marked as not assessed, and failed tests persist until a passing retest.",
  },
  {
    icon: GitBranch,
    title: "Signed CI/CD Gates & Verified Runtime Incidents",
    body: "Pipelines verify expiring signed release receipts at deploy time. Production event bridges separate synthetic HMAC test traffic from live traffic and open incidents only on tool-side verified unauthorized effects.",
  },
];

const PIPELINE_STEPS = [
  ["1", "Register & Connect", "Choose an adapter (assureops-http-json-v1 or assureops-mcp-reference), declare origin/methods, prove ownership, and store Fernet-encrypted synthetic actor credentials."],
  ["2", "Verify Connection", "Automated checks validate destination policy, health, manifest availability, ownership proof, credentials, and whether every profile test fits the authorized scope."],
  ["3", "Governed Profile", "Propose tests from reviewed catalogue templates with typed arguments (never arbitrary code). Separation of duties requires proposer ≠ activator."],
  ["4", "Frozen Release & Sandbox", "Manifest collection freezes release identity. Each step executes once per trial in a disposable, origin-pinned, redirect-free runner with zero platform secrets."],
  ["5", "Change Invalidation", "New releases invalidate only evidence tied to changed components. Unmapped changes or partial analysis trigger conservative retesting."],
  ["6", "Runtime Event Bridge", "Sequenced events with source identity and HMAC run tokens distinguish test runs from live traffic; only tool-side verified unauthorized effects open incidents."],
  ["7", "CI/CD Release Gate", "CI queries /v1/integration/release-gate/check for an exact commit SHA and receives an expiring signed receipt that revokes automatically on new incidents or releases."],
];

const CONTROLS = [
  ["C01", "Access Control", "Privileged operations and data require an authenticated actor with the right role; anonymous or forged identities are rejected."],
  ["C02", "Workspace Isolation", "One tenant's data, documents, and actions never reach another tenant across any request or retrieval path (enforced with PostgreSQL RLS)."],
  ["C03", "Approval Gate", "Consequential writes need a valid, unexpired, single-action approval bound to the exact payload, requester, and release."],
  ["C04", "Tool Usage", "Only registered tools and destinations are reachable, within declared policy and step-budget limits."],
  ["C05", "Prompt Injection", "Instructions embedded in untrusted content cannot hijack behavior or trigger unauthorized tool calls."],
  ["C06", "Data Privacy", "Seeded canary secrets and sensitive credentials never appear in outputs to unauthorized parties."],
  ["C07", "Execution Control", "Agent runs stop deterministically at declared step, time, and cost budgets."],
  ["C08", "Retry Safety", "Retries and duplicate deliveries of supported writes take effect at most once via atomic reservation and external idempotency keys."],
  ["C09", "Output Grounding", "Answers cite permitted supporting sources verbatim and abstain when sources do not answer."],
  ["C10", "Release Traceability", "The running release is identifiable and matches the assessed manifest and runtime event stream."],
];

const AI_PHASES = [
  ["A", "Requirement extraction", "granite4:micro (3B)", "openai/gpt-oss-20b", "200-case v2: 0.94 valid, 0.944 recall, 0 critical"],
  ["B", "Dependency mapping", "phi4-mini (3.8B)", "Off (reviewed rule map)", "External models abstained (<0.4 floor); rule map active"],
  ["C", "Test plan proposal", "qwen2.5-coder:1.5b", "openai/gpt-oss-120b (C-4)", "200-case v2: 0.89 valid, 0.904 recall, 0 critical"],
  ["D", "Semantic evidence NLI", "nli-deberta-v3-small", "Private CPU only", "Never sent externally; numeric hallucination guard active"],
  ["E", "Incident analysis", "phi4-mini (3.8B)", "openai/gpt-oss-20b", "200-case v2: 0.96 valid, 0.997 recall, 0 critical"],
  ["F", "Report explanation", "smollm2:1.7b", "openai/gpt-oss-20b", "200-case v2: 1.00 valid, 0 critical; no derived math"],
  ["G", "Input screening", "—", "llama-prompt-guard-2-86m", "200-case v2: 1.00 accuracy, 0 critical"],
  ["R", "Document retrieval", "bge-small-en-v1.5 + BM25", "Private CPU only", "Held-out recall@3: 0.94 dense vs 0.865 RRF vs 0.805 BM25"],
];

const ARCHITECTURE_LAYERS = [
  { icon: Network, name: "Portals & BFF", path: "apps/customer-web, apps/staff-web", detail: "Next.js 16 standalone apps sharing packages/ui; browsers talk only to server-side BFF routes holding Redis AOF sessions." },
  { icon: Terminal, name: "FastAPI Core", path: "apps/api, packages/domain", detail: "Customer (/v1), Staff (/v1/staff), and Integration/Runtime (/v1/integration, /v1/runtime) APIs with deterministic rules and RLS." },
  { icon: Database, name: "Durable Execution & Store", path: "apps/worker, infra/compose", detail: "PostgreSQL 16 (source of truth + transactional outbox + NOBYPASSRLS), Celery 5.4 workers, Redis 7, and SeaweedFS S3 evidence store." },
  { icon: Cpu, name: "AI & MCP Subsystems", path: "packages/ai, packages/integrations/mcp", detail: "Holdout-gated AI phase router (Ollama / CPU encoders / opt-in Groq) plus acme-refund-tools Streamable HTTP MCP server & fail-closed gateway." },
];

const MCP_TOOLS = [
  ["search_docs(query, workspace)", "Workspace-scoped knowledge search returning trust tags (curated vs untrusted_upload)."],
  ["get_action_status(order_id, action_id)", "Read-only lookup against the SQLite refund ledger."],
  ["issue_refund(order_id, amount_minor, action_id, approval_id)", "Idempotent write (action_id UNIQUE) that independently verifies action & approval with AssureOps before committing and emitting refund_committed."],
  ["export_customers()", "Admin-only export endpoint used to verify role-based access enforcement."],
];

export default async function DocsPage() {
  const api = await probeApiHealth();

  return (
    <div className="mx-auto max-w-6xl space-y-12 pb-12 text-ink">
      {/* Top Bar */}
      <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line bg-surface px-5 py-4 shadow-sm">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2 font-bold text-brand-700 hover:text-brand-800">
            <span className="grid size-9 place-items-center rounded-lg bg-brand-50">
              <ShieldCheck className="size-5" aria-hidden />
            </span>
            AssureOps AI
          </Link>
          <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-800">/docs · Technical Whitepaper</span>
        </div>

        <nav aria-label="Documentation sections" className="flex flex-wrap items-center gap-3 text-sm">
          <a href="#pitch" className="rounded-md px-2 py-1 text-muted hover:bg-brand-50 hover:text-ink">Overview</a>
          <a href="#architecture" className="rounded-md px-2 py-1 text-muted hover:bg-brand-50 hover:text-ink">Architecture</a>
          <a href="#controls" className="rounded-md px-2 py-1 text-muted hover:bg-brand-50 hover:text-ink">Controls</a>
          <a href="#ai-mcp" className="rounded-md px-2 py-1 text-muted hover:bg-brand-50 hover:text-ink">AI &amp; MCP</a>
          <a href="#cicd" className="rounded-md px-2 py-1 text-muted hover:bg-brand-50 hover:text-ink">CI/CD</a>
          <Link href="/auth/login?returnTo=/overview" className="rounded-lg border border-line px-3 py-1.5 font-medium hover:bg-brand-50">
            Customer Sign In
          </Link>
          <Link href="/contact?plan=trial" className="rounded-lg bg-brand-700 px-3.5 py-1.5 font-medium text-white hover:bg-brand-800">
            Free Trial
          </Link>
        </nav>
      </header>

      {/* 1. Pitch & Live Status */}
      <section id="pitch" className="scroll-mt-8 grid gap-6 lg:grid-cols-[1.45fr_1fr]">
        <div className="rounded-2xl border border-line bg-surface p-7 shadow-sm">
          <p className="inline-flex items-center gap-2 rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-800">
            <BadgeCheck className="size-3.5" aria-hidden /> Continuous Readiness Assurance for AI Applications
          </p>
          <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
            Know what your AI app actually proved, what changed, and what must retest before shipping.
          </h1>
          <p className="mt-4 text-base leading-relaxed text-muted">
            Teams deploying tool-using AI agents face an expensive tradeoff: a single prompt, model, retrieval, or tool change can silently break safety or authorization invariants—yet re-running full manual reviews on every release stalls delivery, and single aggregate &ldquo;safety scores&rdquo; create false confidence.
          </p>
          <p className="mt-3 text-base leading-relaxed text-muted">
            <strong className="text-ink">AssureOps AI</strong> turns assurance into a deterministic, CI/CD-native workflow. Models only propose requirements, dependency links, test templates, and explanations after passing synthetic holdout qualification; fixed domain rules, isolated sandboxes, and independent human reviewers govern every verdict and release gate.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/auth/login?returnTo=/overview" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-800">
              Launch Customer Portal <ArrowRight className="size-4" aria-hidden />
            </Link>
            <a href="https://staff.assureops-ai.rafidahad.me" className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2.5 text-sm font-semibold hover:bg-brand-50">
              Staff Reviewer Portal
            </a>
          </div>
        </div>

        {/* Live System Dashboard */}
        <aside aria-label="Live system telemetry" className="flex flex-col justify-between rounded-2xl border border-line bg-surface p-6 shadow-sm">
          <div>
            <div className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-lg font-bold">
                <Activity className="size-5 text-brand-700" aria-hidden /> Live System Status
              </h2>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${api.ok ? "bg-brand-100 text-brand-800" : "bg-amber-50 text-amber-800"}`}>
                <CheckCircle2 className="size-3.5" aria-hidden /> {api.label}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted">Real-time server probe against internal FastAPI `/health` ({api.checkedAt})</p>

            <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl border border-line bg-canvas p-3">
                <dt className="text-xs text-muted">Control Catalog</dt>
                <dd className="mt-0.5 font-bold text-ink">C01–C10 (10)</dd>
              </div>
              <div className="rounded-xl border border-line bg-canvas p-3">
                <dt className="text-xs text-muted">AI Pipeline Phases</dt>
                <dd className="mt-0.5 font-bold text-ink">A–G &amp; R (8)</dd>
              </div>
              <div className="rounded-xl border border-line bg-canvas p-3">
                <dt className="text-xs text-muted">MCP Reference Tools</dt>
                <dd className="mt-0.5 font-bold text-ink">4 Tools (:8720)</dd>
              </div>
              <div className="rounded-xl border border-line bg-canvas p-3">
                <dt className="text-xs text-muted">Identity &amp; Storage</dt>
                <dd className="mt-0.5 font-bold text-ink">Keycloak + S3 + RLS</dd>
              </div>
            </dl>
          </div>

          <div className="mt-5 rounded-xl border border-line bg-canvas p-3.5 text-xs text-muted">
            <p className="font-semibold text-ink">Boundary Notice</p>
            <p className="mt-1">Readiness reports describe verified evidence within an explicit tested boundary and profile—never blanket certifications.</p>
          </div>
        </aside>
      </section>

      {/* Value Pillars */}
      <section aria-label="Core value proposition" className="grid gap-5 md:grid-cols-3">
        {VALUE_PILLARS.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.title} className="rounded-2xl border border-line bg-surface p-6 shadow-sm">
              <div className="grid size-10 place-items-center rounded-xl bg-brand-50 text-brand-700">
                <Icon className="size-5" aria-hidden />
              </div>
              <h2 className="mt-4 text-lg font-bold">{item.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">{item.body}</p>
            </div>
          );
        })}
      </section>

      {/* 2. Architecture & 7-Stage Flow */}
      <section id="architecture" className="scroll-mt-8 space-y-6">
        <div>
          <p className="text-sm font-semibold text-brand-700">System Architecture</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Seven-stage assurance lifecycle &amp; platform topology</h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ARCHITECTURE_LAYERS.map((layer) => {
            const Icon = layer.icon;
            return (
              <div key={layer.name} className="rounded-2xl border border-line bg-surface p-5 shadow-sm">
                <div className="flex items-center gap-2.5">
                  <span className="grid size-9 place-items-center rounded-lg bg-brand-50 text-brand-700">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <div>
                    <h3 className="font-bold">{layer.name}</h3>
                    <p className="font-mono text-[11px] text-muted">{layer.path}</p>
                  </div>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-muted">{layer.detail}</p>
              </div>
            );
          })}
        </div>

        <div className="rounded-2xl border border-line bg-surface p-6 shadow-sm">
          <h3 className="flex items-center gap-2 text-lg font-bold">
            <Workflow className="size-5 text-brand-700" aria-hidden /> End-to-End Execution Flow
          </h3>
          <ol className="mt-4 grid gap-3 md:grid-cols-2">
            {PIPELINE_STEPS.map(([num, title, desc]) => (
              <li key={num} className="flex gap-3 rounded-xl border border-line bg-canvas p-4">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-700 text-xs font-bold text-white">{num}</span>
                <div>
                  <p className="font-semibold text-ink">{title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{desc}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* 3. Control Catalog & Invariants */}
      <section id="controls" className="scroll-mt-8 space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-brand-700">Control Catalog (agentops-controls-v1)</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Ten structured controls with strict security invariants</h2>
          </div>
          <p className="text-xs text-muted">Controls outside an app&apos;s active profile remain visibly marked as <em>not assessed</em>.</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {CONTROLS.map(([id, name, desc]) => (
            <div key={id} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
              <span className="inline-block rounded bg-brand-50 px-2 py-0.5 font-mono text-xs font-bold text-brand-800">{id}</span>
              <h3 className="mt-2 text-sm font-bold">{name}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted">{desc}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-4 rounded-2xl border border-line bg-surface p-6 shadow-sm md:grid-cols-2">
          <div className="flex gap-3">
            <Lock className="mt-0.5 size-5 shrink-0 text-brand-700" aria-hidden />
            <div>
              <h3 className="font-bold">Multi-Tenant Isolation &amp; Secret Hygiene</h3>
              <p className="mt-1 text-sm text-muted">
                Tenant tables enforce composite foreign keys and PostgreSQL row-level security (`NOBYPASSRLS`). Target actor credentials are Fernet-encrypted at rest, and `validation.minimize` masks API keys and emails before external dispatch.
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <ShieldAlert className="mt-0.5 size-5 shrink-0 text-brand-700" aria-hidden />
            <div>
              <h3 className="font-bold">Separation of Duties &amp; Atomic Approvals</h3>
              <p className="mt-1 text-sm text-muted">
                Profile proposer ≠ activator; staff reach tenant data only through an active case assignment; one approval authorizes one logical action via atomic reservation, reconciling ambiguous outcomes rather than re-executing.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 4. AI Phases, Retrieval & MCP */}
      <section id="ai-mcp" className="scroll-mt-8 space-y-6">
        <div>
          <p className="text-sm font-semibold text-brand-700">AI Depth, Benchmarks &amp; Protocol Design</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Holdout-qualified AI phases &amp; MCP tool verification</h2>
        </div>

        <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
          <div className="border-b border-line px-6 py-4">
            <h3 className="flex items-center gap-2 font-bold">
              <Bot className="size-5 text-brand-700" aria-hidden /> AI Phase Routing &amp; Qualification Evidence (200-case v2 holdout suite)
            </h3>
            <p className="mt-1 text-xs text-muted">
              Every phase stays disabled until its exact prompt, schema, and model digest passes synthetic holdout qualification with 0 critical false-support errors.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-canvas text-xs uppercase text-muted">
                <tr>
                  <th className="px-4 py-3">Phase</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3">Local CPU / Ollama</th>
                  <th className="px-4 py-3">Groq Route</th>
                  <th className="px-4 py-3">Observed Benchmark</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {AI_PHASES.map(([phase, role, localModel, groqModel, bench]) => (
                  <tr key={phase}>
                    <td className="px-4 py-3 font-mono font-bold text-brand-800">{phase}</td>
                    <td className="px-4 py-3 font-medium">{role}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">{localModel}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">{groqModel}</td>
                    <td className="px-4 py-3 text-xs text-muted">{bench}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl border border-line bg-surface p-6 shadow-sm">
          <h3 className="flex items-center gap-2 text-lg font-bold">
            <FileCheck2 className="size-5 text-brand-700" aria-hidden /> Reference MCP Integration (`acme-refund-tools` v0.2.0)
          </h3>
          <p className="mt-2 text-sm text-muted">
            Built with the official Python MCP SDK (`mcp 2.3.0`) over <strong className="text-ink">Streamable HTTP</strong> (`/mcp`, port `8720`), reused across the Reference Refund Agent (releases R1–R3 + LLM-driven L1), the zero-LLM Enforcement Gateway, and the AssureOps MCP Connector. Before committing side effects, `issue_refund` verifies the reserved `action_id` and `approval_id` directly against the AssureOps API and enforces SQLite `action_id UNIQUE` idempotency.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {MCP_TOOLS.map(([sig, desc]) => (
              <div key={sig} className="rounded-xl border border-line bg-canvas p-4">
                <p className="font-mono text-xs font-bold text-brand-800">{sig}</p>
                <p className="mt-1 text-xs text-muted">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 5. CI/CD & Production Deployment */}
      <section id="cicd" className="scroll-mt-8 rounded-2xl border border-line bg-surface p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-xl font-bold">
          <GitBranch className="size-5 text-brand-700" aria-hidden /> Continuous Integration, E2E Verification &amp; VPS Deployment
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-line bg-canvas p-4">
            <h3 className="font-semibold">CI Quality &amp; Security Gate (`ci.yml`)</h3>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Runs reversible Alembic migrations (`upgrade -&gt; downgrade -1 -&gt; upgrade`), 148 backend unit/integration/security tests, OpenAPI-to-TypeScript drift checks, `pip-audit`, `secret_scan.sh`, Next.js lint/typecheck/build, `npm audit`, and Playwright + Axe WCAG 2.1 AA browser journeys.
            </p>
          </div>
          <div className="rounded-xl border border-line bg-canvas p-4">
            <h3 className="font-semibold">Automated CD (`cd-vps.yml`)</h3>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Builds immutable `assureops-app`, `assureops-encoder`, `assureops-customer-web`, and `assureops-staff-web` images to GHCR after CI succeeds on `main`, deploys over SSH via `scripts/deploy/vps_deploy.sh`, runs health probes, and auto-rolls back on failure.
            </p>
          </div>
          <div className="rounded-xl border border-line bg-canvas p-4">
            <h3 className="font-semibold">Live Production Topology</h3>
            <ul className="mt-1 space-y-1 text-xs text-muted">
              <li>Customer Portal: <a className="font-medium text-brand-700 underline" href="https://assureops-ai.rafidahad.me">assureops-ai.rafidahad.me</a></li>
              <li>Staff Portal: <a className="font-medium text-brand-700 underline" href="https://staff.assureops-ai.rafidahad.me">staff.assureops-ai.rafidahad.me</a></li>
              <li>OIDC Auth (Keycloak + MFA): <span className="font-mono">auth.assureops-ai.rafidahad.me</span></li>
              <li>TLS Edge: Caddy 2.8.4 (Let&apos;s Encrypt); internal DB/Redis/S3 bound to loopback only.</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
