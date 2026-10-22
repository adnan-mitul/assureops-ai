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
| P5 model phases | Verified, with limits | Lifecycle with shadow/canary/active and rollback (0012); per-workspace admission; qualification tiers (quick 20, compact 50, standard 75, v2 200). R, D (D-2) and G (G-2) qualified on held-out sets; A, B, C, E, F served on their v1 qualifications (C also passed a quick check) |
| P6 Groq | Verified | Adapter, policy and contract tests, live synthetic runs (F qualified on v1; G run on v2 with rate-limit backoff); late replies after cancellation are discarded |
| P7 REA and monitoring | Verified | Unchanged since the integration plan; reviewed incident closure |
| P8 journeys | Verified | Fresh-account browser journey from inquiry to published report (recorded); staff admin (roles, workload, inquiries, reassignment); risk acceptance; inbox; evidence bundle export; WCAG 2.1 AA checks (axe) with fixes |
| P9 delivery and hosted ops | Partly verified | CI: tests, audit, contract drift, browser journeys with video, model qualification matrix, signed images on `main`. Local staged promotion and rollback. **Not done:** hosted HTTPS environments, GitHub App registration, PITR, on-call, measured SLAs (need infrastructure and accounts) |
| P10 AI value and usefulness | Partly done | 200-scenario change benchmark across three arms (results below); v2 qualification suites. **Not done:** buyer interviews, pilots, external users, an independently developed application, comparison with an existing platform. These need real people and are not claimed. |
| P11 handover | Drafted | User and operator guides, generated prompt library, acceptance register, submission package draft (owner fields marked), recorded journey |

## Model results on the v2 suites

| Phase | Model | Result | Decision |
|---|---|---|---|
| D | nli-deberta-v3-small | D-1: accuracy 0.92, 1 critical false support in 300 pairs (route disabled). D-2 on fresh v3: accuracy 0.933, 0 critical | qualified with D-2 (see follow-up below) |
| R | bge-small-en-v1.5 | recall@3: dense 0.94, hybrid 0.865, BM25 0.805 | qualified; dense chosen on the development split (dev: dense 1.0, fusion 0.717, BM25 0.417) |
| G | Prompt Guard 2 86M (Groq) | G-1 (threshold 0.5): accuracy 0.73, 54 of 101 attacks missed. G-2 (threshold 0.0008, set on dev): 75 held-out cases, accuracy 1.0 | qualified with G-2 (see follow-up below) |
| C, A, B, E, F | as pinned | v2 suites built | to run on the CI models matrix (`qualify_suite=v2`) |

## Change benchmark (200 scenarios)

`scripts/change_benchmark_200.py` ran 200 documented configuration mutations of the reference agent's R1 (`profiles/qualification/change-scenarios-v1.json`). It used an isolated bench copy of the reference stack and took 90.6 minutes. Ground truth: every test re-run on every variant, compared with two identical R1 baselines (no flaky tests). 15 tests per scenario.

| Split | Arm | Tests retested | Saving vs full | Missed affected tests | Critical misses | False alarms |
|---|---|---|---|---|---|---|
| development (60) | full retest | 900 | 0 % | 0 | 0 | 822 |
| | reviewed rule-only map | 569 | 36.8 % | 4 | 1 | 495 |
| | rule map + phase B (Phi-4-mini) links | 539 | 40.1 % | 4 | 1 | 465 |
| held out (140) | full retest | 2100 | 0 % | 0 | 0 | 1920 |
| | reviewed rule-only map | 1371 | 34.7 % | 11 | 0 | 1202 |
| | rule map + phase B links | 1265 | 39.8 % | 12 | 0 | 1097 |

What it shows:
- Selective retesting saves 35–40 % of test runs, but it is **not** free of misses. Every miss traces to two missing edges in the reviewed coverage contract: T-C09-01 (citation) also depends on `policy:permission`, and T-C03-03 also depends on `tools:registry`.
- The AI arm saves about 5 points more but missed one more test (V144). Its extra link removed the conservative full-retest fallback that had been covering the missing edge. More mapping is not automatically safer.
- Both edges were found from the development split only and added to the contract (`profiles/coverage/refund-agent.mcp-reference.json`, with a revision note). The held-out split is then re-run (below). Existing activations keep their recorded edges until their profile is re-activated.
- The 30 % saving is a research target. These numbers come from configuration mutations of one reference application, not from real customer change history.

## Follow-up, 22 October 2026 (evening)

**Corrected edges are live.** The reference application's profile revision 2 was proposed by `owner@acme.test` and activated by `reviewer@acme.test`. Activation added `policy:permission -> T-C09-01` and `tools:registry -> T-C03-03` as accepted edges. R1 was then re-collected and fully assessed: all 15 tests ran with current evidence, 13 supported and the two C09 tests awaiting their required review.

**Change benchmark, quick tier (40 held-out scenarios, every mutation operator at least twice, edges synced from the corrected contract, 18.1 min, no flaky tests):**

| Arm | Tests retested (of 600) | Saving vs full | Misses | Critical misses |
|---|---|---|---|---|
| reviewed rule-only map | 364 | 39.3 % | 0 | 0 |
| rule map + phase B links | 356 | 40.7 % | 0 | 0 |

The misses of the earlier held-out run are gone on this subset. A 40-scenario subset is a routine check, not the full held-out measurement, so the 140-scenario re-run remains the result of record to repeat.

**"Inconclusive" test outcome (reference evaluator 1.1.0).** A test that needs an attempt to observe enforcement now reports `inconclusive` when the agent never makes it. T-C04-01 covers an agent that never calls the unregistered tool (the LLM planner can only name allowlisted tools). T-C07-01 covers an agent that stops on its own before the run budget. Inconclusive reads as `unverified`: it never supports a control, never blocks as a failure, never opens or closes a finding, and is never reused for a later release. One real failure among the trials still makes the run `failed`.

**Phase D (decision rule D-2) qualified.** Small NLI models largely ignore numbers. v2's only critical case read "within 6 days" as supporting "within 36 days". D-2 (`validation.nli_signal`) never reads a claim as entailed when it names a number or identifier the premise lacks. The rule was designed after seeing v2, so D was qualified on a fresh 300-pair draw (v3, new seed): accuracy 0.933 (95 % CI 0.899–0.956), 0 critical false support (95 % upper bound 1.3 %). On v2 with D-2: accuracy 0.92, 0 critical; reported, not relied on. v3 reuses v2's fact templates, so it tests new values, not new kinds of claims.

**Quick tier (20 cases per phase, a stratified subset of v2).** A pass is stored as `quick_check` and changes nothing. A critical error is stored as `not_qualified` and switches the route off. 0 critical in 20 bounds the true rate only below 16 %.

| Phase | Model | Quick result |
|---|---|---|
| C | qwen2.5-coder:1.5b | passed: recall 0.95, 0 critical (valid rate 0.55) |
| D | nli-deberta-v3-small (D-2) | passed: accuracy 0.85, 0 critical |
| R | bge-small-en-v1.5 | passed: recall@3 dense 0.95, hybrid 0.90, BM25 0.80 |
| F | gpt-oss-20b (Groq) | passed: valid rate 1.0, 0 critical |
| G | Prompt Guard 2 86M (Groq), threshold 0.5 (G-1) | below floor: accuracy 0.60 |
| A, B, E, F (private) | granite4:micro, phi4-mini, smollm2:1.7b | not run; stopped to save CPU time. They keep their existing qualification. |

**Phase F checker fix.** The F false-support check flagged "C06: 0 of 3 tests supported" as a claim of support. That sentence reports the failure correctly. Such wording ("0 of N", "none") now counts as reporting a failure, and the checker still flags real support claims. The false alarm had recorded Groq F as `not_qualified`, which turned the route off.
Groq F was re-run on the quick tier and passed. Its 50-case qualification then hit the free tier's daily cap (200,000 tokens; the stopped 200-case run had used it), so it was stopped before it could record a false failure. Until it is re-run (runbook: model routes), the Groq F route stays off, and the qualified private model serves F.

**Groq.** Groq stays limited to the approved phases F and G, as planned. Private serving is preferred, and workspaces must allow external processing. Generation runs now wait out Groq rate limits (free tier: 8,000 tokens per minute), so a measurement covers every case.

**L1 (model-driven release) re-run.** Two re-runs with evaluator 1.1.0 produced no evidence: every step ended as an infrastructure error, so the results read as unverified, never as failed. The runner allowed 30 s per reply. In Docker, a four-turn LLM-planned reply on this CPU takes longer, especially with two tests sharing one model. The timeout is now `REFERENCE_CHAT_TIMEOUT` (default 120 s). The inconclusive logic itself is covered by `tests/integration/test_inconclusive_outcome.py`; an end-to-end L1 confirmation needs a faster host.

**Reference agent fix.** The LLM planner called the model synchronously inside the agent's event loop. With a slow CPU model, this froze the agent, and its MCP sessions to the tool server timed out. The call now runs in a worker thread.

**Qualification tiers, final.** 200-case runs are no longer routine. Every phase uses the 50-case `compact` tier (zero critical bounds the rate below about 7.1 %). The 75-case `standard` and 200-case `v2` tiers remain for stronger evidence.

**Phase G-2 qualified.** Prompt Guard 2's scores are extreme (on the dev split, benign text scored at most 0.0006 and attacks at least 0.0009), so the 0.5 threshold missed most attacks. G-2 flags at 0.0008, chosen on the development split only. On 75 held-out cases: accuracy 1.0, no missed attacks, no false flags. The route is qualified for workspaces that allow external processing. Screening stays advisory.

**AI-built test plans (any connected application).** `POST /v1/applications/{id}/profiles/ai-plan` (customer portal: **Applications → AI → Build test plan**) assembles one proposed profile revision:
- the accepted phase A requirements and phase C tests from the permitted catalogue;
- the standard gate policy and the mandatory release identity test;
- `not_assessed` for every control without a test;
- conservative dependency links (every test depends on every component until reviewed).

Separation of duties holds throughout:
- The person who builds the plan cannot activate it.
- A phase C acceptance now records the accepting reviewer as the proposer, so they cannot also activate; before, the proposer was recorded as `ai:<id>`.
- AI-added tests need review of their passing evidence.

Phase A now works for a newly connected application without documents: it reads the declared purpose and collected component names as a quotable source. `lab_journey.py --ai-plan` runs a lab end to end this way.

**Live runs of the AI-built plan flow (RefundDesk lab, demo users, private CPU models)** exposed three problems, each fixed:
1. With only a one-line purpose, granite4:micro copied the control catalogue's own descriptions as quotes. Validation rejected them, which is correct. With a short approved policy document, phase A produced quoted requirements for C01, C02, C03, C05 and C09. The user guide now asks for a reference document.
2. One malformed phase C test voided the whole proposal. In the serving path, each test is now checked on its own: tests that cannot run are removed and listed for the reviewer, and the rest are proposed. Qualification still scores the whole output.
3. The catalogue's `scenario` template accepted steps without a name or method, which later crashed connection verification. Its schema and `validate_args` now enforce what the scenario engine needs (named steps with method and path; assertions naming a step and a known operator). Constrained decoding guides the model to that shape too.

Result of the live runs:
- Proven with the real models: the application was registered with only a declared purpose; the reviewer approved a policy document; phase A produced quoted requirements and the reviewer accepted them; the developer built the plan from the accepted proposals; the developer was refused when activating it; the reviewer activated it.
- Not yet: a plan whose AI tests all run. qwen2.5-coder:1.5b chose the free-form `scenario` template for most tests and wrote steps without names or methods. Validation now removes such tests before review, so they never reach a plan, but a run can end with no runnable test proposed.
- Next step: offer phase C only the named templates (auth_required, data_not_disclosed, role_forbidden and so on) and keep `scenario` human-authored. This changes C's prompt (C-3), so C must be re-qualified, about 1.5 to 2 hours on this CPU.

**Nothing predefined about the application under test.** `seed.py --users-only` (or `ASSUREOPS_SEED_APPS=false`) keeps the demo workspaces and users for signing in, but predefines no application. Applications are submitted, connected and planned in the portal. The staff work queue no longer lists hard-coded reviewer accounts; reassignment targets come from the staff directory.

## Fixed defects found during this work

- `POST /invitations` returned a null id.
- The staff Governance page crashed (it read a gate-policy field the API no longer sent).
- A stray role selection could silently promote a member (role changes now need confirmation).
- S3 orphan objects had no age check, so reconciliation would have deleted them at once.
- Customer self-registration was disabled, so invitees without an account could not join.
- Invitation links pointed to a page that did not exist.
- A rollback to an earlier release was not treated as current.
- pip-audit queried PyPI for local packages.
