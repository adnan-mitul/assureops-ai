# Operations runbooks

Short, tested procedures. Each names the signal, the first safe action and how to confirm recovery.
Metrics come from `GET /metrics` (loopback or a `metrics` service credential); every figure is a count,
never customer content.

| Runbook | Signal |
|---|---|
| [Stuck or failing assessments](assessments.md) | `assureops_job_steps_expired_leases > 0`, outbox age rising |
| [Runtime incident](runtime-incident.md) | new `assureops_incidents{state="open"}` |
| [Evidence store outage or integrity failure](evidence-store.md) | evidence `unavailable` in readiness, S3 errors |
| [Model route outage or bad output](model-routes.md) | `assureops_model_calls{status!="succeeded"}` rising |
| [Backup, restore and deletion](backup-restore.md) | scheduled drill, erasure request |
| [Credential rotation and revocation](credentials.md) | suspected leak, staff departure |
