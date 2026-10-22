# Model route outage or bad output

Models only propose. Failures leave work `pending`, `unavailable` or `review_required`, never accepted.

* **Private serving down:** phases report `unavailable`. There is no automatic switch to an external provider.
* **Groq errors:** `rate_limited` and `timeout` retry with a bound. `auth_failed` or `model_unavailable` means the key was revoked or the model removed: set `GROQ_ENABLED=false`, run `scripts/groq_models.py`, pin a model and re-qualify with `scripts/qualify_phase.py --record`.
* **Bad output:** `unsupported_claims` and `invalid_output` are already blocked from acceptance. If their rate rises, record a new qualification run; a `not_qualified` record disables the route.
* **Budget:** daily external token budget per workspace (`GROQ_DAILY_TOKEN_LIMIT_PER_WORKSPACE`); model jobs run on their own queue with concurrency 1.

## Route lifecycle (development → holdout → shadow → canary → active)

Staff **Governance → Model route lifecycle** (operators and admins change stages; senior reviewers can read):

| Move | Gate enforced by the API |
|---|---|
| development → holdout | none (registration of an exact provider:model) |
| holdout → shadow | a current qualification record for that exact model, prompt and schema; private routes only (external routes never shadow customer data) |
| holdout → canary | the same qualification gate (shadow is optional) |
| shadow → canary | ≥ 5 shadow runs with valid-output rate ≥ 0.75 |
| canary → active | ≥ 5 canary runs, no invalid output, valid rate ≥ 0.75, approved by a different person than the one who started the canary |

- A managed **active** route replaces the environment-configured model for that phase. A **canary** serves a stable share of requests (`canary_percent`, default 10 %, by request id). A **shadow** sees the same inputs after each served result. Its outputs are stored as `shadow`, never served, reviewed or listed to customers; only its counts feed the promotion gate.
- **Rollback**: `POST /v1/staff/admin/model-routes/phases/<phase>/rollback`. The active route becomes `rolled_back` and the route it replaced becomes active again. With no previous managed route, the phase returns to its environment-configured model. Every model still needs its qualification record to serve.
- **Fair admission**: each workspace may have at most `AI_MAX_QUEUED_PER_WORKSPACE` (default 12) phase requests pending or running; more are refused with `429 queue_full`. Inference hosts keep one loaded model and one request at a time (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`).

## Qualification tiers

| Tier | Command | Cases | What a result means |
|---|---|---|---|
| quick | `qualify_phase.py --phase X --provider ... --model ... --suite quick --record` | 20 per phase, a stratified subset of v2 (`scripts/gen_holdouts_quick.py`) | A routine check. A pass is stored as `quick_check` and never qualifies a route or replaces its qualification. A critical error is stored as `not_qualified` and switches the route off. Zero critical errors in 20 cases only bounds the true rate below about 16 % (95 %). |
| mini | `--suite mini` | 10 per phase, stratified from v2 | The fastest qualification, chosen by the project owner for CPU hosts. Zero critical errors in 10 bounds the rate only below about 27.8 %. Use compact or larger before relying on a route. |
| compact | `--suite compact` | 50 per phase, stratified from v2 | The routine qualification tier (used for every phase since 22 October). Zero critical errors bounds the rate below about 7.1 %. |
| standard | `--suite standard` | 75 per phase, stratified from v2 | A stronger routine tier (below about 4.9 %); G-2 is qualified on it. |
| v2 | `--suite v2` | 200 held out (300 for D) | Release-grade evidence, for a faster machine. Zero critical errors bounds the rate below about 1.9 % (1.3 % with 300 cases). |
| v3 (D only) | `--suite v3` | 300, fresh seed (`scripts/gen_holdouts_d_v3.py`) | D's qualification after the D-2 rule was designed against v2 (see below). |

The change benchmark has the same split: `change_benchmark_200.py --quick` runs 40 held-out scenarios that cover every mutation operator at least twice. The full 140 held-out scenarios remain the measurement of record.

## Phase D decision rule (D-2)

The NLI model's top label is used, with one deterministic exception (`validation.nli_signal`): a claim that names a number or identifier missing from the premise is never read as entailed. That exception is what fixed v2's only critical case ("within 6 days" read as supporting "within 36 days"). The rule only moves labels away from support, and the signal shows it as `guard`. D-2 was designed after seeing v2, so D's qualification of record is the fresh v3 draw; v2 results with D-2 are reported, not relied on.

## Phase G decision threshold (G-2)

Prompt Guard 2's injection probabilities are extreme: on the development split (60 cases), benign text scored at most 0.0006 and attacks at least 0.0009, so the old 0.5 cut-off missed most attacks while flagging nothing. G-2 flags at 0.0008 (`registry.SCREEN_THRESHOLD`). The threshold was chosen on the development split only. On 75 held-out cases it caught every attack with no false flags, and the route is qualified. A flag only asks for review; screening never blocks or authorizes anything.

## Groq free-tier limits

For `openai/gpt-oss-20b` the free tier allows 8,000 tokens per minute, 1,000 requests per day and 200,000 tokens per day. One phase F case uses about 1,100 tokens, so a 50-case run needs about 55,000 tokens and roughly 10 minutes. When the daily cap is reached, runs wait out the rate limit, and a run that cannot answer every case records `not_qualified`. Stop it and re-run after the window resets:

    python scripts/qualify_phase.py --phase F --provider groq --model openai/gpt-oss-20b --suite compact --record
