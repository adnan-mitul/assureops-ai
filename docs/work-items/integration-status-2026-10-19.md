# Integration plan status — updated 21 October 2026

Baseline: commit `61610d5` (first milestone). This records what `AssureOps-Remaining-Integration-Plan.md` steps I1–I8 and the LLM phases do now, how each was verified on this machine (4-core i7-8650U, 16 GB RAM, no GPU), and what is still outside this environment. "Verified" means exercised by tests or an end-to-end run here.

## Results on the supplied labs

Both labs were connected and assessed through the generic HTTP adapter with their own profiles (no lab-specific runner code), private S3 evidence and disposable runners.

| | RefundDesk | DocVault |
|---|---|---|
| Profile | 16 tests; assessed C01, C02, C03, C08, C10 | 13 tests; assessed C01, C02, C05, C06, C09, C10 |
| Not assessed (shown in gate, dashboard and report) | C04, C05, C06, C07, C09 | C03, C04, C07, C08 |
| R1 full assessment | all 16 supported, gate ready | 11 supported, DV01/DV05 await review |
| R2 (seeded fault) | 7 stale, 9 reused; RF01, RF05, RF06, RF07, RF11 fail (confirmed against the tool-side ledger); gate blocked | 9 stale, 4 reused; DV02, DV03, DV04, DV06, DV08 fail; gate blocked |
| Matches the lab's own `verify.py` | yes | yes |
| Live request on R2 through the event bridge | one verified C03 incident | one verified C02 incident |
| Platform test traffic misread as live | 0 | 0 |
| R3 retest, reviewed closure, independent publication | done | done |
| Change benchmark | 7 of 16 retested (56 % fewer) | 9 of 13 retested (31 % fewer) |
| Full re-run: critical misses among reused evidence | 0 | 0 |
| Disposable runner containers on an internal network | 16/16 pass, public egress refused | 13/13 pass, public egress refused |
| Source analysis (REA 6.7.0 + built-in collector) | 8 routes; code:target and code:transport match the manifest; REA Evidence recorded (coverage partial: Python is not REA's scope) | 9 routes; both code components match; REA Evidence recorded |

## AI phases (all served and qualified on their planned models)

| Phase | Model and serving | Qualification (synthetic holdout, 0 critical false support required) | Run on the labs, 21 October (`scripts/run_ai_phases.py`) |
|---|---|---|---|
| A requirements | Granite-4.0-micro, local Ollama | A-2: control recall 0.94, 2/4 outputs fully quote-verified | RefundDesk: proposed, accepted by a second person. DocVault: quoted control text not present in the source, so held as unsupported and rejected |
| B dependencies | Phi-4-mini, local Ollama | B-2: 3/3 valid, link recall 0.4 (weak; links stay proposals) | RefundDesk: accepted, 3 edge proposals created. DocVault: accepted, no new edges |
| C tests | Qwen2.5-Coder-1.5B, local Ollama | C-2: 3/3 valid, control recall 1.0 | Both: accepted, created a proposed profile revision (activation stays with a human) |
| D evidence | DeBERTa-v3-small NLI, local encoder | D-1: accuracy 0.75 on atomic claims | RefundDesk: review required, accepted. DocVault: proposed, accepted |
| E incidents | Phi-4-mini, local Ollama | E-2: retest recall 1.0, 1/2 fully supported | Both: a quote not present in the verified event was detected; the result could only be rejected (weakest phase) |
| F explanation | SmolLM2-1.7B local (F-3: 6/8 valid); Groq gpt-oss-20b as approved external route (F-3: 8/8 valid) | qualified on both routes | Both: report explanation drafted locally by SmolLM2 and accepted; backend numbers and verdicts unchanged |
| R retrieval | BGE-small, local encoder, hybrid with BM25 | recall@3 hybrid 1.0 vs BM25 0.5 | source search and phase A source selection use hybrid |
| G screening | Prompt Guard 2 (86M), Groq | accuracy 0.875 | Both: injection text 0.9992 flagged, benign 0.0004 |

Models only propose; every output is schema- and source-validated, decoding is constrained to the identifiers each request may use, and a different person accepts or rejects. Results with unsupported claims cannot be accepted. Acceptance only creates further proposals (edges, profile revisions). A qualified private route always wins; a private outage is reported as unavailable, never routed externally. CI re-qualifies the private phases weekly against the pinned artifacts (`models` job).

## Step status

| Step | Status | Evidence |
|---|---|---|
| **I1** correctness | Verified | Release identity (version + component hash); frozen job revisions; lease renewal; locked finalization; poison completion; cancellation; reconciler back-off; ambiguous writes reconciled from the system of record and never re-sent; evidence hash checks and deletion history; publication drift checks. |
| **I2** connectors | Verified | Versioned adapter contract; generic HTTP/JSON adapter (demo alias) and MCP reference adapter; 12 templates; per-application profiles with separation of duties; connection verification; encrypted revocable credentials; baseline profile generator; onboarding UI. |
| **I3** private data and execution | Verified | Private S3 with integrity checks; Redis sessions (AES-GCM, survive Redis restarts with append-only persistence); staff MFA (TOTP + `amr`, survives a fresh realm import); subprocess and container runners (internal network, no platform secrets); quotas and rate limits. |
| **I4** AI services | Verified | All phases served locally or via approved Groq routes, qualified with exact artifact records, run on lab data through durable leased jobs, reviewed in the portal. |
| **I5** Groq | Verified | Phases F and G; key server-side only; workspace opt-in; typed failures; usage records without keys or prompts. |
| **I6** REA and monitoring | Verified | REA pinned (`rea-agents@6.7.0`, commit `559af3d3`, npm integrity and entry hash) and run in a scrubbed process; event bridge with source credentials, epochs, sequences, heartbeats and a durable spool; cohort checks; reviewed incident closure. |
| **I7** CI/CD | Verified | GitHub Actions on PR #1: tests, reversible migrations, pip-audit, secret scan, portal build, browser journeys (12 Playwright tests over both portals, Keycloak MFA and the BFF, with per-run generated test values) and a weekly/dispatch private-model qualification job (checksum-pinned Ollama, digest-checked models and encoders, synthetic holdouts, no secrets). Local digest promotion staging → canary → production, rollback, and a broken image stopped at staging; exact-SHA gate with expiring receipts; signed webhook; commit statuses (mock-tested). |
| **I8** qualification and operation | Verified locally | Phase holdouts; change benchmark with ground-truth false alarms and misses; backup/restore drill; Prometheus with alert rules; load: ~91 events/s ingestion (p95 13 s per 100-event batch), gate check p95 ~1 s; recovery: worker killed mid-assessment, job completed 129 s later (lease 120 s); runbooks. |

## Limits of this environment

- Measurements come from one laptop CPU shared with model inference; hosted sizing must be measured on the target infrastructure.
- Image signing and registry push run only on `main` in GitHub Actions; no hosted staging/production target is configured, so promotion is demonstrated locally.
- No GitHub App registration exists; gate decisions are posted as commit statuses with a server-side token when configured (mock-tested). Registering the App needs the repository owner's account.
- Signed images, SBOM and provenance run on pushes to `main`, so they run for the first time when PR #1 merges.
- Phase B link recall (0.4) and phase E quote fidelity are weak on these small CPU models; their outputs stay proposals and unsupported results cannot be accepted.
- The labs cannot serve an ownership verification token, so ownership stays a declared gap.

## Rollback notes

Migrations `0006`–`0008` downgrade cleanly (CI checks one-step downgrade). Downgrading `0006` restores the old release key and fails if two releases share a component hash. Disabling a model route: remove its `PRIVATE_MODEL_<phase>`/`GROQ_MODEL_<phase>` or record a `not_qualified` run; the phase reports unavailable. `EVIDENCE_BACKEND=fs` makes S3 evidence unavailable rather than supported. `STAFF_MFA_REQUIRED=false` is for development only.
