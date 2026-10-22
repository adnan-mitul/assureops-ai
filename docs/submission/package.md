# Submission package (draft)

Draft of the eight submission sections required by plan v6 P11. Every claim links to evidence in this repository. Items marked **[owner to complete]** need facts only the team has. Nothing here invents collaborators, pilots, awards, users or measured savings.

## 1. Basics

- **Name:** AssureOps AI: evidence-based readiness assessment for AI agent applications.
- **Team / contact:** [owner to complete]
- **Repository:** private GitHub repository `adnan-mitul/assureops-ai` (shared on request).
- **Status:** working product on a local single-machine deployment; hosted operation not yet set up (see section 4 limits).

## 2. Problem

Teams ship AI agents that take real actions (refunds, data access, tool calls), but cannot show, release by release, which safety requirements were actually tested. They also can't tell when that evidence stopped being valid after a change. Manual reviews are slow and are redone from scratch for every release. Generic LLM evaluations measure answer quality, not whether an agent can be pushed into an unauthorized action.

## 3. Solution

- **Assessment against reviewed requirements:** each application gets its own reviewed profile (controls, tests, applicability reasons). Tests run as catalogue templates in disposable sandboxes pinned to the application's origin. Results keep separate dimensions (result, evidence validity, runtime), never one score.
- **Evidence that goes stale honestly:** each release's identity is frozen. A change invalidates only the evidence that depends on it, and unmapped changes force full retesting. A redeployed earlier release becomes current again.
- **Independent review and publication:** an analyst drafts, a different reviewer publishes the exact snapshot, and the customer downloads a hashed evidence bundle.
- **Release gate:** CI asks about an exact commit and receives a signed, expiring decision that new incidents invalidate. Pull requests are judged on their merge candidate.
- **Runtime monitoring:** an event bridge with source identity, epochs and sequences. Only tool-side verified unauthorized effects open incidents.
- **AI assistance, never AI decisions:** eight small models propose requirements, dependency links, tests, evidence signals, incident summaries and explanations. Each runs privately, is qualified per phase, and goes through a development, holdout, shadow, canary and active lifecycle. A person other than the requester accepts every proposal.
- **Reach:** a private connector (relay) for targets inside a customer network; per-application developer assignment; an in-app inbox; risk acceptance that never rewrites a failure.

## 4. Demonstration and links

- **Recorded journey:** `e2e/journey.spec.ts` runs a fresh owner and developer from public inquiry to a published report through both portals. Video files go to `var/e2e-videos/` locally and are attached to every CI run as the `browser-journeys` artifact. That is a recording of an automated run, not a live session.
- **Supplied labs:** RefundDesk and DocVault, R1 → R2 (seeded faults detected) → R3 (fixed, retested, published). See `docs/work-items/integration-status-2026-10-19.md`.
- **Model-driven target:** release L1 of the reference agent uses a real local LLM. It was assessed with 15 tests, and the failures are real model behaviour; see `docs/work-items/model-driven-target-2026-10-22.md`.
- **Change benchmark (200 scenarios):** see `docs/work-items/v6-completion-status.md`.
- **Limits:** no hosted environment, no GitHub App registration, and no external users or pilots yet. Measurements come from one laptop CPU.

## 5. Data and AI provenance

- **Data:** all evaluation data is synthetic (generated suites in `profiles/qualification/`, synthetic lab applications). No customer evidence, real credentials or real money anywhere in the repository.
- **Models (all small and pinned):**

| Phase | Model | Serving | Licence |
|---|---|---|---|
| A | IBM Granite 4.0 Micro (3B) | Ollama, local | Apache-2.0 |
| B, E | Microsoft Phi-4-mini (3.8B) | Ollama, local | MIT |
| C | Qwen2.5-Coder-1.5B | Ollama, local | Apache-2.0 |
| D | cross-encoder/nli-deberta-v3-small | local encoder service | Apache-2.0 |
| F | SmolLM2-1.7B (private); gpt-oss-20b via Groq (approved exception) | Ollama / Groq | Apache-2.0 |
| R | BAAI/bge-small-en-v1.5 | local encoder service | MIT |
| G | Llama Prompt Guard 2 (86M) | Groq | Llama 4 Community License |

- Exact artifacts (Ollama digests, Hugging Face revisions and weight digests) are pinned in `profiles/qualification/model-pins.json` and `packages/ai/assureops_ai/encoder_pins.json`, and verified in CI.
- **Qualification honesty:** on the larger v2 suites, phase D (1 critical false support in 300 pairs) and phase G (accuracy 0.73) do **not** qualify, so their routes are disabled. Phases A, B, E and F have v2 suites built but not yet run at full size.

## 6. Tooling and IDE disclosure

The platform was built with **Claude Code** (Anthropic), used as an AI coding agent under the team's direction, in the Claude desktop app. Commits it authored carry a `Co-Authored-By: Claude` trailer. [owner to complete: any other editors or tools the team used]

## 7. MCP disclosure

- The reference target uses the **Model Context Protocol** (MCP Python SDK, MIT): a controlled MCP tool server and a synthetic refund agent that calls it through the AssureOps enforcement gateway.
- AssureOps itself does not expose an MCP server to customers. The adapter `assureops-mcp-reference` assesses MCP-based targets.

## 8. Prompt library

`docs/ai/prompt-library.md` is generated from the prompts and schemas the code actually sends (`scripts/export_prompt_library.py`).

## Rubric mapping

| Criterion (weight) | Evidence |
|---|---|
| Innovation (20 %) | Change-aware evidence reuse with conservative fallback; model lifecycle with shadow and canary; private relay; model-driven target assessment |
| Technical (20 %) | RLS multi-tenancy, leases and fencing, outbox, signed receipts, sandboxed runners; 112+ backend tests and 25 browser journeys; CI with audit, contract drift check, signed images |
| Business / global readiness (20 %) | Two-portal product with onboarding from inquiry to report; hosted operation, pricing and pilots are **not yet evidenced** [owner to complete] |
| Impact / ethical AI (20 %) | Models never decide outcomes; honest disabling of models that fail larger suites; scores are evidence support, not "safety" |
| Scalability / NRB (10 %) | Measured local limits only; NRB or international contribution: [owner to complete, with permission to name the contributor] |
| Presentation (10 %) | Recorded journey, user and operator guides, this package |
