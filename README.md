# AssureOps AI

Continuous readiness assurance for tool-using AI agents: know which requirements an AI application has demonstrated, when a change invalidates that evidence, and what must be reassessed. Built to `AssureOps-AI-Production-Execution-Plan-v5.md`; this repository implements the plan's first working milestone (§45.1). See `docs/work-items/milestone-w4-status.md` for exactly what is verified, in progress or deferred.

Readiness reports describe evidence within a tested boundary. They are not certifications.

## Architecture

| Part | Path | Port | Role |
|---|---|---|---|
| PostgreSQL 16, Redis 7, Keycloak 26 | `infra/compose` | 5441, 6391, 8780 | Authoritative state with row-level security, job transport, OIDC identity |
| AssureOps API | `apps/api` | 8700 | Customer, staff and integration surfaces |
| Worker and outbox dispatcher | `apps/worker` | — | Durable, fenced execution of the approved test catalog |
| Domain rules | `packages/domain` | — | Reducer, reuse predicate, approvals, findings, events, cases, migrations |
| Reference MCP integration | `packages/integrations/mcp` | 8720, 8710 | Controlled MCP tool server and the synthetic refund agent behind the enforcement gateway |
| Customer portal | `apps/customer-web` | 3700 | Customer-company workflows |
| Staff portal | `apps/staff-web` | 3710 | Assigned AssureOps analysts, reviewers, case managers, operators |
| Shared design system | `packages/ui` | — | Components, evidence drawer, OIDC/BFF helpers |
| Profile and coverage | `profiles` | — | Versioned C01–C10 profile, gate policy, reviewed dependency edges |

## First run

```bash
python scripts/render_realm.py
docker compose --env-file infra/compose/dev.env -f infra/compose/docker-compose.yml up -d
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
npm install
.venv/Scripts/python scripts/seed.py --reset
.venv/Scripts/python scripts/render_web_env.py
bash scripts/start_services.sh
npm run dev:customer
npm run dev:staff
```

Customers sign in to the Keycloak realm `assureops`, staff to `assureops-staff` (see `docs/decisions/0002-separate-identity-realms.md`).

`infra/compose/dev.env` holds generated local test values (database roles, client secrets, the shared test-account password, service tokens). It is git-ignored. Test accounts: `owner@acme.test`, `dev@acme.test`, `reviewer@acme.test`, `viewer@acme.test`, `dev@globex.test` (customer portal); `analyst@assureops.test`, `reviewer@assureops.test`, `manager@assureops.test`, `operator@assureops.test` (staff portal).

## Demo journey (plan §22, §45.1)

1. Customer (`dev@acme.test`): Dashboard → Demo deploy R1 → Full assessment. 14 of 15 tests decide automatically; C09 semantic results wait for a reviewer.
2. Customer: Assessment Cases → submit a case. Staff (`manager@`): assign `analyst@` and `reviewer@`.
3. Customer: Demo deploy R2 (seeded fault: approval threshold typed with extra zeros) → the change invalidates 7 tests, 7 are reused → Run required retests → four approval tests fail, gate Blocked.
4. Customer: Runtime Incidents → simulate `refund 2500 for order C-2041` → the tool server reports an unapproved refund → verified incident.
5. Customer: Demo deploy R3 (fix) → retest passes; test findings resolve from retest evidence; the gate stays blocked until a reviewer closes the runtime incident with evidence.
6. Staff analyst: accept C09 evidence, draft the report. Staff reviewer: close the incident, publish the report. Customer: the published report shows its frozen snapshot plus a separate current-status banner.

`scripts/journey_check.py` runs steps 1, 3, 4 and 5 headlessly against running services.

## Checks

```bash
bash scripts/verify/verify.sh
```

Backend tests run against the real database with the runtime role: tenant isolation, approval binding and concurrency, evidence validity, runtime classification and fencing.

## Honest scope
AI model routes are implemented as disabled configuration only; no model is qualified and none decides any status. The agent's planner is deterministic. REA, the GitHub App, customer CI gates, production CI/CD, S3 storage, sandboxed runners and staff MFA are later work packages. See `docs/decisions/0001-local-development-topology.md`.
