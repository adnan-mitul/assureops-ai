# AssureOps operator guide

For the people who install and run AssureOps. Incident procedures are in [runbooks](../runbooks/README.md).

## Components

| Component | Process | Default address |
|---|---|---|
| API | `uvicorn assureops_api.main:app` | 127.0.0.1:8700 |
| Assessment worker | `celery ... -Q assessments` (concurrency 1) | — |
| AI/analysis worker | `celery ... -Q ai,analysis` (concurrency 1) | — |
| Outbox dispatcher | `python -m assureops_worker.dispatcher` (dispatch, reconcile, notifications, daily evidence maintenance) | — |
| Customer / staff portals | Next.js (`next start`) | 3700 / 3710 |
| PostgreSQL, Redis, Keycloak, SeaweedFS (S3), Prometheus | `infra/compose` | 5441, 6391, 8780, 9100, 9190 |
| Private inference | Ollama (generation) and `assureops_ai.encoder_server` (embedding/NLI) | 8740 / 8730 |
| Reference target (demo) | MCP tool server and synthetic refund agent | 8720 / 8710 |

PostgreSQL is the source of truth; Redis only schedules work and holds portal sessions with append-only persistence.

## First installation

```bash
python scripts/init_dev_env.py        # generates local test values into the git-ignored dev.env (never printed)
python scripts/render_realm.py && python scripts/render_storage.py
docker compose --env-file infra/compose/dev.env -f infra/compose/docker-compose.yml up -d
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt && npm ci
.venv/Scripts/python scripts/seed.py --reset && .venv/Scripts/python scripts/render_web_env.py
bash scripts/start_services.sh
```

To test without any predefined application, seed with `scripts/seed.py --reset --users-only`, or set `ASSUREOPS_SEED_APPS=false` for the Docker `migrate` step. The demo workspaces and users still exist for signing in, but every application is submitted in the portal, connected and given an AI-built or baseline test plan by its own users. New customers can also sign up themselves (registration is open in the customer realm).

Hosted environments replace `dev.env` with a secret manager, enable SMTP with `verifyEmail` in the customer realm, use HTTPS with Secure cookies, and set `STAFF_MFA_REQUIRED=true` (the default).

### Everything in Docker

`bash scripts/docker_up.sh` runs the same components as containers (`infra/compose/full-stack.yml`):

- The image `assureops-app` runs `api`, `worker`, `ai-worker`, `dispatcher`, `tools`, `agent` or `migrate` (schema, idempotent seed and an object store round trip). Its siblings are `assureops-encoder` and `assureops-customer-web` / `assureops-staff-web`.
- All containers share one network namespace, so `dev.env` and the rendered portal env files apply unchanged and the Keycloak issuer is identical for browsers and services.
- Processes that listen on 127.0.0.1 only (tool server, encoder, Ollama, labs) are published through `loopback-relay`, which forwards the namespace's interface address to loopback on the same port. If a port is published but the host gets no answer, check that the relay is running and lists that port.
- On Windows, run the script from Git Bash. If lab paths need `MSYS_NO_PATHCONV=1`, the readiness checks still work, because they never pass `/dev/null` to the native curl.
- Secrets are mounted at run time; images contain none.
- Model weights are mounted read-only (`ASSUREOPS_MODELS_DIR`).
- The project name and named volumes match `docker-compose.yml`, so data carries over when switching modes.

## Daily operation

- **Operations page** (staff portal) shows outbox depth and age, job states, expired leases, ingestion rate, inference routes and runner isolation. It shows counts only, never customer content.
- **Administration page** (admins and case managers): staff roles (granted by another admin, never by the person themselves; the last admin cannot be removed), workload, and inquiries.
- **Model routes**: Governance → *Model route lifecycle*. Models pass through stages, and every promotion is gated by the API; see [model-routes runbook](../runbooks/model-routes.md). Qualify with `scripts/qualify_phase.py` (`--suite v2` for the 200-case suites), or on GitHub with the `models` matrix job (`workflow_dispatch`, `qualify_phases`, `qualify_suite`).
- **Evidence maintenance**: daily in the dispatcher; on demand with `python scripts/evidence_maintenance.py` (report only) or `--apply`.
- **Backups**: `scripts/backup_restore_check.py` (database dump plus hashed object copy, restore drill into a scratch key).
- **Private connector**: see [private-connector runbook](../runbooks/private-connector.md).

## Limits and admission

- Assessments per workspace per day: `workspaces.assessments_per_day` (50 by default).
- AI phase requests queued per workspace: `AI_MAX_QUEUED_PER_WORKSPACE` (12); more get `429 queue_full`.
- External model tokens per workspace per day: `GROQ_DAILY_TOKEN_LIMIT_PER_WORKSPACE`.
- Inference hosts serve one loaded model and one request at a time.
- Measured on one laptop CPU (not a hosted SLA): about 91 ingested events/s, release-gate check p95 about 1 s, worker crash recovery about 129 s with a 120 s lease.

## Checks before a release

```bash
bash scripts/verify/verify.sh      # migrations, compile, secret scan, tests, profiles, types, lint
npm run test:e2e                   # browser journeys, including the fresh-account journey
```

CI runs the same checks plus a dependency audit, an OpenAPI contract drift check, browser journeys with video, and signed images on `main`.
