# Integration plan status — 19 October 2026

Baseline: commit `61610d5` (first milestone). This records what `AssureOps-Remaining-Integration-Plan.md` steps I1–I8 now do, how each was verified on this machine, and what is still open. "Verified" means exercised by tests or an end-to-end run here; "configured" means implemented but not exercised against a real external system.

## Results on the supplied labs

Both labs were connected and assessed through the generic HTTP adapter with their own profiles (no lab-specific runner code), on a clean database, private S3 evidence and disposable subprocess runners.

| | RefundDesk | DocVault |
|---|---|---|
| Profile | 16 tests; assessed C01, C02, C03, C08, C10 | 13 tests; assessed C01, C02, C05, C06, C09, C10 |
| Not assessed (shown in gate, dashboard and report) | C04, C05, C06, C07, C09 | C03, C04, C07, C08 |
| R1 full assessment | all 16 supported, gate ready (support 50 %, coverage 50 %) | 11 supported, DV01/DV05 await review |
| R2 (seeded fault) | 7 tests stale, 9 reused; RF01, RF05, RF06, RF07, RF11 fail, each confirmed against the tool-side ledger; gate blocked | 9 stale, 4 reused; DV02, DV03, DV04, DV06, DV08 fail; gate blocked |
| Matches the lab's own `verify.py` | yes (same five failures) | yes (same five failures) |
| Live request on R2 through the event bridge | one verified C03 incident | one verified C02 incident |
| Platform test traffic misread as live | 0 (HMAC run tokens) | 0 (declared synthetic identities inside step windows) |
| R3 retest | all pass; incident closed by an independent reviewer with current evidence | all pass; DV01/DV05 accepted by reviewer; incident closed |
| Publication | independent reviewer published; drafter could not | same |
| Change benchmark (R1→R2, R2→R3) | 7 of 16 retested (56 % fewer) | 9 of 13 retested (31 % fewer) |
| Full re-run on R3: critical misses among reused evidence | 0 | 0 |

Commands: `scripts/lab_journey.py`, `scripts/change_benchmark.py --full-check`, `scripts/backup_restore_check.py`.

## Step status

| Step | Status | Evidence |
|---|---|---|
| **I1** correctness | Verified | Release identity is (version, component hash) (`uq_release_identity`); jobs freeze release/environment/profile/test digests/evaluator/connection (`assessments.frozen`); lease renewal during runner execution; locked finalization; poison steps finalize; cancellation marks pending steps and finalizes; evidence hash verified on every read and availability check; deletion history; publication refused on new incidents, changed evidence, profile change or newer release. Tests: `test_profiles_and_identity.py`, `test_attribution_and_poison.py`, `test_fencing.py`, `test_object_store.py`. |
| **I2** connectors | Verified | Adapter contract (`collect_manifest`, `validate_connection`, `run_allowed_test`, `read_action_evidence`, `normalize_event`); `assureops-http-json-v1` (alias `assureops-http-demo-v1`) and `assureops-mcp-reference`; 12 permitted templates; per-application profiles with separation of duties; connection checks for destination, health, manifest, ownership, credentials, events and profile scope; encrypted, revocable credentials; baseline profile generator for any HTTP/JSON AI app; customer connect page and staff profile review. |
| **I3** private data and execution | Verified locally | Private S3 (SeaweedFS) with integrity checks and no anonymous access; Redis portal sessions sealed with AES-256-GCM (survive portal restarts); staff MFA (Keycloak TOTP + `amr` claim enforced by the staff API, checked in the browser); disposable runners: subprocess with scrubbed environment (default) or container image (`infra/runner`, built and checked: no platform variables, metadata targets refused); egress pinned to the connection origin, redirects refused, private targets only when allowed; per-day assessment quota and Redis rate limits on ingestion and AI requests. Network-level egress allowlisting for containers needs the hosting firewall/proxy. |
| **I4** AI services | Implemented; no model served | Phase registry A–G/R with prompts, output schemas, validation (schema, quoted spans, fact references, stray numbers, certification claims), BM25 retrieval, durable leased/fenced phase jobs on a concurrency-1 queue, model-call records without keys or prompts, review flow where acceptance only creates further proposals (edges, profile revisions). No private inference endpoint is configured here, so every private route reports `no_route_configured`. |
| **I5** Groq | Verified live for phase F | Server-side provider with typed failure states, bounded retries, JSON-schema mode for supporting models, low reasoning effort for gpt-oss, workspace opt-in, daily token budget, redaction before dispatch. The account offers no general text model at or under 3.8B, so `openai/gpt-oss-20b` was pinned under an explicit, recorded size exception (`GROQ_SIZE_EXCEPTION_MODEL`) for phase F only. Qualification: prompt/schema F-1 was **not qualified** (3/8 schema-invalid because of a section cap, validator false positives on negated "not a certification" and an "except C03" sentence, plus genuinely derived counts); after fixing only those validator defects and tightening the prompt (F-2: copy numbers, never derive them), the full 8-case holdout gave 8/8 valid, 0 unsupported claims, 0 critical false support, median 1.6 s, and the record was stored. Live run: an explanation draft for the published RefundDesk report came back `proposed` (request ID, token usage, prompt version recorded; no key or prompt stored), the developer could not approve it, and a reviewer accepted it. All other phases stay `no_route_configured`. |
| **I6** REA and monitoring | Verified (built-in collector); REA not installed | Analysis runs from authorized zip snapshots; source/build identity compared with manifest fingerprints; unknown components make the release partial and broaden retesting; REA runs only when pinned. Event bridge with source credentials, epochs, contiguous sequences with explicit gaps, heartbeats and a durable SQLite spool; expected-cohort mismatch flagged in coverage; blocked attempts never incidents; violations grouped per control and cohort; reviewed closure. |
| **I7** CI/CD | Workflows written; not run on GitHub | CI: backend tests with Postgres/Redis/S3, reversible-migration check, pip-audit, secret scan, portal typecheck/lint/build, npm audit; signed images with SBOM and provenance; digest-based staging → canary → production with environment gates and rollback; manual model-qualification workflow. Customer side: CI credentials, exact-SHA gate with expiring signed receipts re-validated at deploy time, signed and deduplicated GitHub webhook. Tests: `test_release_gate.py`. Posting check runs to GitHub needs the App's private key. |
| **I8** qualification and operation | Partly verified | Change benchmark and full re-run miss check (above); backup/restore drill passed (47 tables, 61 objects by hash); `/metrics`; runbooks in `docs/runbooks`. Load/recovery limits on hosted infrastructure and phase holdout results for served models are not measured yet. |

## Still open

- Re-qualify phase F whenever the pinned Groq model, prompt or schema changes; phases A–E, R and G still need private inference hosts.
- Serving the private candidate models on inference hosts and running their phase holdouts.
- Installing and pinning REA; a real GitHub App (private key) to post check runs.
- Hosted deployment target for the promotion workflow, network egress policy for container runners, load and recovery measurements.
- Strong ownership proof for the labs (they cannot serve a verification token, so ownership stays a declared gap).

## Rollback notes

Migrations `0006` and `0007` downgrade cleanly (CI checks one-step downgrade). Downgrading `0006` restores the old `(application, manifest_hash)` release key and fails if two releases now share a component hash, which is the defect it fixed. Turning off S3 (`EVIDENCE_BACKEND=fs`) makes S3-stored evidence unavailable rather than supported. `STAFF_MFA_REQUIRED=false` relaxes the staff API check for development only.
