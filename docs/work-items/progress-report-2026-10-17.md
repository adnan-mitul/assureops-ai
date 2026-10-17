# AssureOps AI — Progress report

**Date:** 17 October 2026
**Specification:** `AssureOps-AI-Production-Execution-Plan-v5.md` (section numbers below refer to it)
**Scope delivered:** the plan's first working milestone (§45.1), built to the plan's stack and rules. The UI follows the approved dashboard design image; all behaviour follows the plan.

> Honest summary: the full milestone journey works end to end in the browser across both portals, on the real stack (PostgreSQL with RLS, Celery/Redis outbox, Keycloak OIDC, real MCP). **No AI model is connected yet**: all model routes are configured but disabled, and every decision is made by deterministic tests, rules and human reviewers. Nothing is committed to git (the folder is not a git repository).

---

## 1. What was done today

### 1.1 Planning and analysis
- Read and analysed the full v5 plan (all 46 sections), the business plan (§19), the judging criteria (§20) and the AI Builders Congress site (InfraSphere AI → AgentOps challenge, 6 criteria, 8 submission sections, YouTube demo requirement).
- Gap analysis of the first prototype against the plan; the prototype was then replaced.
- Produced a demo dashboard mockup; the final UI follows the dashboard design image supplied.

### 1.2 Infrastructure (§7, §35)
| Item | Status |
|---|---|
| Docker Compose: PostgreSQL 16.4, Redis 7.4, Keycloak 26.0.7 (`infra/compose`) | Running |
| Separate DB roles: `assureops_owner` (migrations) and `assureops_app` (runtime, no superuser, no BYPASSRLS) | Done, tested |
| Local test secrets generated into git-ignored `infra/compose/dev.env` | Done |
| Two identity realms: `assureops` (customers) and `assureops-staff` (staff), separate clients and audiences | Done (`docs/decisions/0002`) |

### 1.3 Domain and database (`packages/domain`) (§6, §8, §10, §11, §14, §27)
- 25+ tables with Alembic migrations (0001–0005); tenant tables carry `workspace_id`, composite foreign keys, and **row-level security on 24 tables** (FORCE, transaction-scoped context).
- Versioned control profile `profiles/agentops-v1.json`: C01–C10, 15 approved tests, gate policy, evidence freshness, approval threshold.
- Coverage contract `profiles/coverage/refund-agent.mcp-reference.json` with reviewed dependency edges, mandatory components and runtime sources.
- **Reducer** with separate state dimensions: control result (supported/failed/unverified/review_required), evidence validity (current/stale/unavailable), finding state, job state, runtime coverage, gate (blocked/incomplete/ready).
- **Reuse predicate**: identical fingerprints, same reviewed edge set, same profile version, no unmapped or partial collection, not expired, evidence available; otherwise stale.
- **Change impact**: combined component diff, affected tests/controls, conservative full retest for unmapped components or partial collection, stable retest plan IDs.
- **Scores per §27**: evidence support % and evidence coverage %, with counts; readable gate reason.
- **Approval protocol (§10)**: one approval = one logical action, bound to application, environment, release, tool schema hash, normalized payload (integer minor units), policy version and requester; atomic row-locked reservation; self-approval rejected; ambiguous outcome stays bound and is reconciled, never re-executed.
- Findings: open / under_review / resolved / reopened; resolution only through passing retest evidence or an audited reviewer determination.
- Runtime events (§12): authenticated sources, epochs and sequences, duplicate/conflict quarantine, gap detection, blocked attempt ≠ violation, only tool-side verified unapproved writes open incidents; explicit, revision-checked, reviewed incident closure.
- Case workflow (§33.5): draft → submitted → triage → assessment → awaiting_customer/awaiting_review → published → monitoring → reassessment.
- Private content-addressed evidence store with hashes and tombstones.

### 1.4 API (`apps/api`) (§9, §33.6)
- **Customer surface** (`/v1/...`): applications, releases (manifest collection with gaps), change sets and retests, assessments (202, idempotency keys, cancel, progress feed), findings and reviews, evidence, approvals, monitoring, cases, published reports with separate current status, settings, demo helpers.
- **Staff surface** (`/v1/staff/...`): work queue, claim, assignment and revocation, case workspace, investigation and coverage reviews (edge propose/accept/reject with separation of duties), evidence requests, internal vs customer-visible messages, semantic evidence review, finding decisions, report draft, independent review and publication, incidents and closure, operations (metadata only), governance.
- **Integration surface**: gateway action reserve/transition, tool-server action confirmation, runtime event ingestion.
- Identity: OIDC JWT validation (issuer, audience, expiry, signature); roles from database memberships, never from the token or browser; service and source credentials stored only as hashes.
- Typed errors with request IDs; `Cache-Control: private, no-store`.

### 1.5 Worker (`apps/worker`) (§11)
- Transactional outbox → dispatcher → Celery; steps claimed with database-time leases and increasing fencing tokens; stale workers cannot commit; one committed result per step; reconciler re-enqueues expired or unclaimed steps; poison handling.
- Test runner: 15 approved tests over C01–C10, each checking the **tool-side record via MCP**, not only the agent's reply; identity check that the running release matches the assessed manifest.
- Assessment traffic is recognised only when it carries the ID of a step AssureOps is actually running.

### 1.6 Reference integration (`packages/integrations/mcp`) (§12)
- Real **MCP tool server** (MCP SDK 2.3.0, protocol 2026-07-28): `search_docs`, `get_action_status`, `issue_refund`, `export_customers`; confirms every write with AssureOps, enforces unique action IDs, reports tool-side events.
- **Enforcement gateway**: role, allowlist, live MCP schema, run budget, approval reservation; fails closed when AssureOps is unreachable.
- Synthetic refund agent with releases R1 (correct), R2 (seeded fault: approval threshold typed with extra zeros), R3 (fix); live manifest with component fingerprints and negotiated MCP version.

### 1.7 Portals (`apps/customer-web`, `apps/staff-web`, `packages/ui`) (§33, §34)
- Shared design system (plan tokens), evidence drawer (observed facts / test outcome / AI hypotheses / reviewer decisions kept separate), status vocabulary per state dimension, no-access page.
- BFF per portal: PKCE login, server-side sessions, per-portal cookies, CSRF on mutations, token refresh, path allowlists.
- **Customer portal** (15 routes): dashboard (design image), applications, releases, changes, assessments and live progress, findings, evidence, runtime incidents (with demo traffic and approval panels), reports with print, assessment cases, settings.
- **Staff portal** (8 routes): work queue, case workspace, investigation, review queue, review and publication checklist, incidents, operations, governance.

### 1.8 Verification
- **28 backend tests pass against the real database with the runtime role**: tenant isolation (T02), approval binding and concurrent claimers (T03/T04), evidence validity and change impact (T11/T12), runtime classification and gaps (T14), fencing (T13).
- Both portals: TypeScript and ESLint clean. `scripts/verify/verify.sh` passes.
- **Browser journey completed**: R1 full assessment → case submitted → manager assigns analyst and reviewer (self-review blocked) → R2 retest finds 4 approval failures, gate Blocked → live unapproved refund opens incidents on cohort R2 → R3 retest passes, gate still blocked by incidents → analyst confirms C09 semantic evidence → reviewer closes incidents with evidence → gate Ready (100% support and coverage) → analyst drafts, reviewer publishes → customer sees frozen, hash-verified report plus separate live status.

### 1.9 Bugs found and fixed during verification
- Event reordering produced false sequence gaps → ordered sender and missing-sequence counting.
- Assessment traffic opened false incidents → verified step-ID origin on actions.
- Incidents attributed to the tool server version → action records carry the requesting release.
- Staff could decide findings or close incidents outside their case → case scoping enforced.
- Proposed edges for components not in the manifest; self-confirmation of own-run evidence; missing 404s; staff idempotency → fixed.
- Portals overwrote each other's cookies on localhost → per-portal cookie names.
- Shared SSO realm leaked identities between portals → separate realms.
- Jobs stayed "Queued" while running; new draft reports superseded themselves → fixed.

### 1.10 Documentation
`README.md`, `AGENTS.md`, `docs/decisions/0001-local-development-topology.md`, `docs/decisions/0002-separate-identity-realms.md`, `docs/work-items/milestone-w4-status.md`, `docs/third-party/adoption-register.yaml`, `.github/workflows/ci.yml` (written, not exercised), `.github/CODEOWNERS`.

---

## 2. What is still left

### 2.1 AI models (§13, §43, EX12–EX17, EX19) — not started
- No model is downloaded, served or called. All 8 routes and the Groq adapter are disabled configuration only.
- Needed: inference adapters (`generate`, `embed`, `classify`), model registry and artifact locks, phase prompts and schemas, evaluation corpora (~200 reviewed examples per phase), qualification records, shadow mode, L01–L12 and M01–M16 tests.
- Hardware note: this machine (i7-8650U, 16 GB RAM, no GPU, 20 GB free) can run DeBERTa and BGE on CPU; the 1.5–3.8B generative models only quantized and slowly. A GPU server is the realistic target.

### 2.2 Connecting real customer applications
- No "Connect application" screen; registration via API, credentials via the seed script.
- Test catalog is refund-specific; other app types need their own templates and coverage contracts.
- No installable SDK; no private connector for data-restricted customers (§37.4).

### 2.3 Other planned work packages
| Area | Plan | State |
|---|---|---|
| REA reverse-engineering adapter, artifact upload | §31, EX09 | Not started |
| GitHub App, exact-SHA checks, deploy receipts | §37, EX20 | Not started |
| Platform CI/CD: run CI on GitHub, images, SBOM, signing, staging/production promotion, rollback | §36, EX03, EX21 | Workflow file only |
| Production operations: SLOs, load tests, restore/rollback drills, runbooks | §42, PR01–PR12 | Not started |
| Independent benchmark (200 change scenarios), baselines, pilots, unit costs | §16, §38.4, EX22 | Not started |
| Second controlled application (document agent) | §16 | Not started |

### 2.4 Known local-development deviations (tracked in ADR 0001)
- Evidence on local disk instead of S3-compatible storage.
- Tests run in the worker process, not a disposable sandbox runner.
- Staff MFA not enforced.
- In-memory portal sessions (lost on portal restart).
- Polling instead of SSE progress.
- Hand-written frontend types instead of an OpenAPI-generated client.
- Windows Celery `--pool=solo` (development only).

### 2.5 Smaller follow-ups
- Case state history (the timeline shows only the current stage).
- Work-queue age measured from last update, not submission.
- Cancellation race tests (T13 cases beyond fencing).
- Report `state` vs publication `state` naming.
- Demo sample button sends immediately (sends twice if "Send" is also clicked).
- Initialise git and make the first commit.

### 2.6 Business and competition work (§19, §20, §22)
- Buyer interviews (at least 5), two pilot teams, pricing evidence, competitor comparison.
- NRB / international collaborator contribution.
- Bias-mitigation and KPI section for the Impact criterion; standards mapping (OWASP LLM / Agentic Top 10, NIST AI RMF).
- The 8 submission sections, a 3-minute pitch script and a public/unlisted YouTube demo.
- Confirm the exact submission deadlines with the organiser (the site showed conflicting dates).

---

## 3. How to run it
```bash
docker compose --env-file infra/compose/dev.env -f infra/compose/docker-compose.yml up -d
bash scripts/start_services.sh
npm run dev:customer
npm run dev:staff
```
Customer portal: http://localhost:3700 · Staff portal: http://localhost:3710 · Test account password: `DEMO_USER_PASSWORD` in `infra/compose/dev.env`.

Full checks: `bash scripts/verify/verify.sh`.
