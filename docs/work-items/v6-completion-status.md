# Full Completion Plan v6: status, 22 October 2026

Work on branch `completion-plan-v6` (draft PR adnan-mitul/assureops-ai#2). "Verified" means exercised by recorded tests or runs here; see the generated [acceptance register](../acceptance/register.md). Plan v6 also points to v5 case IDs (T01–T20 and others); the v5 document is not in this repository, so cases are grouped by suite.

## By plan step

| Step | Status | What exists now |
|---|---|---|
| P0 baseline | Verified | Reproducible install (`init_dev_env.py` → render → compose → seed), CI green on every push, status tracked here and in the register |
| P1 correctness | Verified | Release identity, frozen revisions, leases and fencing, cancellation, poison steps, reconciliation, evidence hashes; **new**: a redeployed earlier release becomes current again (migration 0013) |
| P2 onboarding and connections | Verified | Public contact page → staff inquiry conversion → invitation e-mail → self-registration (customer realm only) → accept page; application-scoped developer grants (0009); member management UI; private connector relay (0011); typed frontend contracts generated from OpenAPI with a CI drift check |
| P3 demos and coverage | Verified, with limits | Both labs through AssureOps; reviewed applicability reasons per untested control; model-driven reference release L1 assessed with a real LLM (findings recorded). Full C01–C10 coverage exists only for the reference agent; the labs declare their exclusions. |
| P4 storage, sessions, isolation | Verified | Private S3 with hash checks; retention purge with legal holds and database/object reconciliation; revocation applies on the next request (membership, grant, case assignment, staff role) |
| P5 model phases | Partly verified | Lifecycle with shadow/canary/active and rollback (0012); per-workspace admission. v2 suites (200 held out per phase, 300 for D) built. Results: R qualified (dense chosen on the development split); **D and G not qualified on v2, routes disabled**; C, A, B, E, F v2 runs moved to the CI matrix (CPU time here) |
| P6 Groq | Verified | Adapter, policy and contract tests, live synthetic runs (F qualified on v1; G run on v2 with rate-limit backoff); late replies after cancellation are discarded |
| P7 REA and monitoring | Verified | Unchanged since the integration plan; reviewed incident closure |
| P8 journeys | Verified | Fresh-account browser journey from inquiry to published report (recorded); staff admin (roles, workload, inquiries, reassignment); risk acceptance; inbox; evidence bundle export; WCAG 2.1 AA checks (axe) with fixes |
| P9 delivery and hosted ops | Partly verified | CI: tests, audit, contract drift, browser journeys with video, model qualification matrix, signed images on `main`. Local staged promotion and rollback. **Not done:** hosted HTTPS environments, GitHub App registration, PITR, on-call, measured SLAs (need infrastructure and accounts) |
| P10 AI value and usefulness | Partly done | 200-scenario change benchmark across three arms (results below); v2 qualification suites. **Not done:** buyer interviews, pilots, external users, an independently developed application, comparison with an existing platform. These need real people and are not claimed. |
| P11 handover | Drafted | User and operator guides, generated prompt library, acceptance register, submission package draft (owner fields marked), recorded journey |

## Model results on the v2 suites

| Phase | Model | Result | Decision |
|---|---|---|---|
| D | nli-deberta-v3-small | accuracy 0.92 (95 % CI 0.884–0.946), 1 critical false support in 300 pairs | not qualified; route disabled |
| R | bge-small-en-v1.5 | recall@3: dense 0.94, hybrid 0.865, BM25 0.805 | qualified; dense chosen on the development split (dev: dense 1.0, fusion 0.717, BM25 0.417) |
| G | Prompt Guard 2 86M (Groq) | accuracy 0.73 (95 % CI 0.665–0.787); 54 of 101 attacks missed, 0 false flags | not qualified; optional route disabled |
| C, A, B, E, F | as pinned | v2 suites built | to run on the CI models matrix (`qualify_suite=v2`) |

## Change benchmark (200 scenarios)

Results are filled in when the run finishes (`var/benchmarks/change-benchmark-200.json`).

## Fixed defects found during this work

- `POST /invitations` returned a null id.
- The staff Governance page crashed (it read a gate-policy field the API no longer sent).
- A stray role selection could silently promote a member (role changes now need confirmation).
- S3 orphan objects had no age check, so reconciliation would have deleted them at once.
- Customer self-registration was disabled, so invitees without an account could not join.
- Invitation links pointed to a page that did not exist.
- A rollback to an earlier release was not treated as current.
- pip-audit queried PyPI for local packages.
