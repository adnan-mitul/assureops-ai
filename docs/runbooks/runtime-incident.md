# Runtime incident

Incidents open only from rules marked `violation` in the application's profile, and only for tool-side or
system-of-record sources. Blocked attempts are never incidents. The platform's own assessment traffic is
recognised by HMAC run tokens (strong) or declared synthetic identities inside a step window (weak, flagged
as such on the event). Violations for the same control and release cohort accumulate in one open incident.

1. Open the incident in the staff portal (the case must be assigned to you). Read the linked events and the release cohort.
2. If the affected release is still deployed, ask the customer to roll back or deploy a fix. Deployment receipts issued before the incident are already invalid: `/v1/integration/release-gate/verify` rejects them.
3. Closure needs a different release with current passing evidence for the control and a reviewer note. A generic pass never closes an incident.
4. Recovered when: incident closed, its finding resolved, gate recomputed.
