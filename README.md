# AssureOps AI

Continuous readiness assurance for AI applications: know which requirements an application has demonstrated, when a change invalidates that evidence, and what must be reassessed. Built to `AssureOps-AI-Production-Execution-Plan-v5.md` (first milestone, §45.1) and `AssureOps-Remaining-Integration-Plan.md` (I1–I8). `docs/work-items/integration-status-2026-10-19.md` records what is verified, what is configured but not exercised, and what is left.

Readiness reports describe evidence within a tested boundary. They are not certifications.

## Architecture

| Part | Path | Port | Role |
|---|---|---|---|
| PostgreSQL 16, Redis 7, Keycloak 26, SeaweedFS (S3) | `infra/compose` | 5441, 6391, 8780, 9100 | Authoritative state with row-level security, job transport and portal sessions, OIDC identity (staff MFA), private evidence bucket |
| AssureOps API | `apps/api` | 8700 | Customer, staff, onboarding, AI, delivery (release gate, GitHub webhook) and integration surfaces; `/metrics` |
| Worker and outbox dispatcher | `apps/worker` | — | Durable, fenced, lease-renewed steps; disposable runners; separate model/analysis queue (concurrency 1) |
| Domain rules | `packages/domain` | — | Profiles, reducer, reuse predicate, connections, vault, approvals, findings, events, cases, migrations |
| Connectors | `packages/integrations/connectors` | — | Versioned adapters (`assureops-http-json-v1`, alias `assureops-http-demo-v1`; `assureops-mcp-reference`), egress guard, scenario engine, template catalogue, sandbox runner, event bridge, baseline profiles |
| AI phases | `packages/ai` | — | Phase registry A–G/R, private and Groq providers, prompts, BM25 retrieval, validation, durable phase jobs |
| Source analysis | `packages/integrations/rea` | — | Pinned REA adapter (reported as a gap until installed) and the built-in static collector |
| Reference MCP integration | `packages/integrations/mcp` | 8720, 8710 | Controlled MCP tool server and the synthetic refund agent behind the enforcement gateway |
| Customer and staff portals | `apps/customer-web`, `apps/staff-web` | 3700, 3710 | Next.js 16 with server-side Redis sessions behind each portal's BFF |
| Profiles | `profiles` | — | Control catalog C01–C10, per-application profiles, connection templates, coverage contracts, qualification holdouts |

## How any AI application is checked

1. **Register** the application (owner) and **connect** it: choose an adapter, give the target origin, the paths and methods tests may use, ownership proof and synthetic test-actor credentials (encrypted at rest; only fingerprints are ever shown).
2. **Verify** the connection: destination policy, health, manifest, ownership, credentials, events and whether every profile test fits the authorized scope. Gaps are listed, not hidden.
3. **Profile:** propose a profile (a reviewed file, the template baseline from declared facts, or phase C proposals). Tests are catalogue templates with typed arguments, not code. A different person activates it. Controls without tests stay visible as *not assessed* and count against coverage.
4. **Release:** collecting the manifest freezes identity as (version, component hash). Assessments freeze release, environment, profile, test, evaluator and connection revisions; each step runs once per trial in a disposable runner with no platform secrets and an origin-pinned, redirect-free HTTP client.
5. **Change:** a new release invalidates only evidence whose reviewed dependencies changed; unmapped changes, partial collection or unknown components from source analysis force conservative retesting. Failures stay failures until a passing retest.
6. **Operate:** the event bridge adds source identity, epoch and sequence and delivers durably; platform test traffic is recognised by HMAC run tokens; only tool-side verified unauthorized effects open incidents, and closure is a reviewed decision.
7. **Release gate:** CI asks `/v1/integration/release-gate/check` for an exact commit SHA and receives an expiring signed receipt, re-verified at deployment and invalidated by new incidents, newer releases or profile changes.

## First run

```bash
python scripts/render_realm.py
python scripts/render_storage.py
docker compose --env-file infra/compose/dev.env -f infra/compose/docker-compose.yml up -d
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
npm install
.venv/Scripts/python scripts/seed.py --reset
.venv/Scripts/python scripts/render_web_env.py
bash scripts/start_services.sh
npm run dev:customer
npm run dev:staff
```

`infra/compose/dev.env` holds generated local test values and is git-ignored. Customer accounts: `owner@acme.test`, `dev@acme.test`, `reviewer@acme.test`, `viewer@acme.test`, `dev@globex.test`. Staff accounts: `analyst@assureops.test`, `reviewer@assureops.test`, `manager@assureops.test`, `operator@assureops.test`. Staff sign-in asks for a one-time code: `python scripts/staff_otp.py analyst@assureops.test` prints the current code for the local test authenticator.

## The supplied labs (RefundDesk, DocVault)

Start each lab from its own folder (`python app.py`, ports 8811 and 8812). Then either use the portal (Applications → Register → Connect, with `profiles/connections/<app>.json` and `profiles/applications/<app>.json` as the settings and the reviewed profile), or run the scripted journey:

```bash
.venv/Scripts/python scripts/lab_journey.py --app refunddesk-demo --name RefundDesk --lab-readme <lab folder>/README.md --live-traffic <request.json>
```

It connects, verifies, has a developer propose and a reviewer activate the profile, assesses R1, deploys R2 (stale evidence, dependency-driven retest, preserved failures), sends one live request through the bridge (verified incident), deploys R3, retests, then a staff reviewer accepts evidence that needs review, closes incidents with evidence and publishes. RefundDesk covers C01, C02, C03, C08, C10; DocVault covers C01, C02, C05, C06, C09, C10; every other catalog control is reported as not assessed.

## Models and Groq

Models only propose (requirements, dependency links, catalogue tests, incident summaries, explanation drafts); rules and reviewers decide. Every phase is disabled until its exact model has a qualification record. Phase F (explanation) may use Groq when `GROQ_ENABLED=true`, `GROQ_API_KEY` is set server-side, `GROQ_MODEL_F` is pinned, the workspace owner allows external processing, and `scripts/qualify_phase.py --phase F --provider groq --model <id> --record` qualified that model. `scripts/groq_models.py` lists account models against the project's ≤3.8B constraint; a larger model needs an explicit operator exception (`GROQ_SIZE_EXCEPTION_MODEL`).

## Checks

```bash
bash scripts/verify/verify.sh
.venv/Scripts/python scripts/backup_restore_check.py
.venv/Scripts/python scripts/change_benchmark.py --app refunddesk-demo --full-check
```

Runbooks: `docs/runbooks/`. Customer pipeline example: `docs/integrations/customer-release-gate.yml`.
