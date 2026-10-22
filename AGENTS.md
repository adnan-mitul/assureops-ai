# AssureOps — project instructions

The execution specification is `AssureOps-AI-Production-Execution-Plan-v5.md` (kept outside this repo). Section numbers below refer to it.

## Stack and boundaries
- `apps/api` FastAPI: customer (`/v1/...`, customer token audience), staff (`/v1/staff/...`, staff audience) and integration (`/v1/integration/...`, `/v1/runtime/...`, service or source credentials) surfaces.
- `apps/worker` Celery worker plus outbox dispatcher. PostgreSQL is the source of truth; Redis only schedules.
- `packages/domain` authoritative rules: models, RLS migrations, reducer, approvals, findings, events, cases.
- `packages/integrations/mcp` reference integration: controlled MCP tool server, enforcement gateway, synthetic refund agent (releases R1–R3).
- `packages/integrations/connectors` versioned adapters (generic `assureops-http-json-v1`, `assureops-mcp-reference`), egress guard, scenario engine, permitted template catalogue, sandbox runner, event bridge. Tests are data (templates + typed args); never add code paths for one application.
- `packages/ai` phase registry, providers (private, Groq), prompts, retrieval, validation, durable phase jobs. `packages/integrations/rea` source analysis (pinned REA or built-in collector).
- `apps/customer-web`, `apps/staff-web` Next.js 16 portals sharing `packages/ui`; browsers talk only to their own BFF (`/api/...`), which holds the session server-side.
- `profiles/` control catalog, per-application profiles, connection templates, coverage contracts, qualification holdouts. `infra/compose` Postgres, Redis, Keycloak, SeaweedFS (private S3).

## Commands
- Infra: `docker compose --env-file infra/compose/dev.env -f infra/compose/docker-compose.yml up -d`
- Reset and seed: `.venv/Scripts/python scripts/seed.py --reset`
- Backend services: `bash scripts/start_services.sh` (stop: `powershell -File scripts/stop_services.ps1`)
- Portals: `npm run dev:customer`, `npm run dev:staff`
- Checks: `bash scripts/verify/verify.sh`; browser journeys `npm run test:e2e` (stack and portals running); first run creates test values with `python scripts/init_dev_env.py`
- Lab journeys: `.venv/Scripts/python scripts/lab_journey.py --app <app> --name <Name> --lab-readme <lab>/README.md`
- Drills: `scripts/backup_restore_check.py`, `scripts/change_benchmark.py --app <app> --full-check`; staff OTP for local sign-in: `scripts/staff_otp.py <user>`
- Models: `bash scripts/start_models.sh` (Ollama :8740, encoders :8730; started by start_services.sh), qualify with `scripts/qualify_phase.py --phase X --provider private|groq --model <id> --record`, run phases with `scripts/run_ai_phases.py`; CI qualification against pinned artifacts `scripts/ci_qualify_models.py --phases C D R` (pins in `profiles/qualification/model-pins.json`)
- Evaluation: `scripts/change_scenarios.py` + `scripts/change_benchmark_200.py` (isolated bench stack), `scripts/gen_holdouts_v2.py` + `qualify_phase.py --suite v2`, `scripts/retrieval_decision.py`, `scripts/model_target_check.py` (LLM-driven reference release L1)
- Docs from code: `scripts/export_prompt_library.py`, `scripts/export_openapi.py && npm run gen:api`, `scripts/acceptance_register.py` (after pytest `--junitxml var/test-results/pytest.xml` and Playwright `--reporter=json`)
- Isolation, limits, delivery: `scripts/container_runner_check.py`, `scripts/load_recovery_check.py load|recovery`, `scripts/deploy/local_promote.py promote|rollback`; monitoring config `scripts/render_monitoring.py`

## Rules that must not regress
- No model decides pass/fail, evidence validity, approvals or release gates (§13.1). Model routes stay disabled until qualified.
- Separate state dimensions; never one green/red field (§6). Scores are "evidence support/coverage", never "safety" (§27).
- Evidence reuse only through the reuse predicate; unmapped or partial collection forces conservative retest (§5, §14).
- One approval authorizes one logical action; reservation is atomic; ambiguous outcomes reconcile, never re-execute (§10).
- Runtime: blocked attempt ≠ violation; only tool-side verified unauthorized effects open incidents; closure is explicit and reviewed (§12).
- Staff reach tenant data only via an active case assignment; separation of duties for publication and edge acceptance (§33).
- Tenant tables keep `workspace_id`, composite FKs and RLS; the runtime role never gets BYPASSRLS (§8).
- Each application is assessed only with its own active profile; controls outside it stay visible as not assessed. Profile proposer ≠ activator.
- Runners get one capsule (one frozen test, scoped credentials) and no platform secrets; requests stay on the connection origin, redirects are refused.
- External model providers receive nothing unless the workspace allows it and the phase/model is qualified; a private outage never enables them.

## Prohibited data handling
- No customer evidence, real credentials or real money in the repo, fixtures or logs. `infra/compose/dev.env` and rendered realm/env files are local test values and git-ignored.

## Definition of done (§45.3)
Domain contract, backend authorization, durable state and errors, both relevant UI paths, migration if needed, observable failure behavior, meaningful tests (including a negative test for security-sensitive work), documentation and rollback notes. Run `scripts/verify/verify.sh`.
