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
