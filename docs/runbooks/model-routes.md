# Model route outage or bad output

Models only propose. Failures leave work `pending`, `unavailable` or `review_required`, never accepted.

* **Private serving down:** phases report `unavailable`. There is no automatic switch to an external provider.
* **Groq errors:** `rate_limited` and `timeout` retry with a bound. `auth_failed` or `model_unavailable` means the key was revoked or the model removed: set `GROQ_ENABLED=false`, run `scripts/groq_models.py`, pin a model and re-qualify with `scripts/qualify_phase.py --record`.
* **Bad output:** `unsupported_claims` and `invalid_output` are already blocked from acceptance. If their rate rises, record a new qualification run; a `not_qualified` record disables the route.
* **Budget:** daily external token budget per workspace (`GROQ_DAILY_TOKEN_LIMIT_PER_WORKSPACE`); model jobs run on their own queue with concurrency 1.
