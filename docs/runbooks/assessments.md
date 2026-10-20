# Stuck or failing assessments

**Signals:** `assureops_job_steps_expired_leases`, `assureops_outbox_oldest_age_seconds`, assessments stuck in `running`.

1. Check the dispatcher and both workers (`var/logs/dispatcher.log`, `worker.log`, `worker-models.log`). PostgreSQL is the source of truth; Redis loss only delays work.
2. The reconciler re-enqueues expired leases and unclaimed steps every 15 s. Stale workers cannot commit (fencing-token check); the runner renews its lease every 10 s while a step runs.
3. A step that exhausts `max_attempts` becomes `failed` (poison) and the assessment finalizes with those tests `unverified`; it never becomes a pass.
4. `identity_mismatch` means the target runs a different release than the one assessed: collect the running release and assess that instead. Not retried.
5. Precondition failures (a setup request returned nothing to capture) and transport errors are `unverified`, not application failures.
6. Recovered when: no expired leases, outbox age near zero, the assessment shows a terminal status.
