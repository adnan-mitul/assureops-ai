# 0001 — Local development topology for the first milestone

Status: accepted for development; revisit at W2/W10.

## Decision
Run PostgreSQL 16, Redis 7 and Keycloak 26 in Docker Compose (`infra/compose`). Run FastAPI, the Celery worker (`--pool=solo` on Windows), the outbox dispatcher, the MCP tool server and the synthetic agent as host processes. Portals run with `next dev`.

## Why
Matches the plan's fixed stack (§7): PostgreSQL with RLS, Celery/Redis with a transactional outbox, a maintained OIDC provider, real MCP. The developer machine is Windows; §35.1 says native Windows Celery behaviour must not be a release dependency, so `--pool=solo` is development-only.

## Deviations from the production plan (tracked, not hidden)
| Area | Plan | Now | Follow-up |
|---|---|---|---|
| Evidence storage | Private S3-compatible object store | Content-addressed files under `var/evidence`, hashes and tombstones in PostgreSQL | Swap `evidence_store` for an S3 client (MinIO in compose) |
| Runner isolation | Disposable hardened sandbox / microVM | Tests run inside the worker process against an allowlisted staging target | Isolated runner work package |
| Staff MFA | Required | Not enforced in local Keycloak | Enable OTP flow for the staff client before any non-local use |
| Sessions | HttpOnly server session | In-memory server-side store per portal process | Durable session store (Redis) for multi-replica deployments |
| Progress feed | Authenticated SSE | Polling of `/v1/assessments/{id}/events` | SSE with reconnect-to-authoritative-state |
| Generated client | OpenAPI-generated TS client | Hand-written response types | Add response models and generate `packages/api-client` |
| Agent model | Real model execution for live claims | Deterministic rule-based planner behind the real gateway and MCP tools | Qualify a small-model route (§13) and label the demo accordingly |

## Verification
`scripts/verify/verify.sh`; `scripts/journey_check.py` exercises R1 → R2 → live violation → R3 against running services.
