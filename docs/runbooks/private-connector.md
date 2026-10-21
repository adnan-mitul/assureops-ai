# Private connector (relay)

Use the relay when the hosted service cannot reach the application under test (private network, laptop, on-premises staging).

## How it works

- The connection sets `"execution": {"mode": "relay"}`. That also lets the connection name a private address; cloud metadata addresses are still refused.
- For every test step the worker queues the step's capsule as a relay task. The capsule holds one frozen test and that connection's test credentials. It is encrypted at rest and the step keeps its lease and fencing token while waiting.
- The relay, run by the customer next to the target, connects outbound only. It claims one task with its application-bound relay credential and runs the task in `python -I -m assureops_connectors.sandbox` with a scrubbed environment. It then posts the result with the claim nonce.
- A claim wipes the stored ciphertext, so a capsule can be handed out once. A result is accepted once, only with the matching nonce, and only before the deadline.
- A missed deadline is recorded as `relay_timeout`. It retries within the step's attempt budget and then ends as unverified evidence, never as a pass.
- Connection verification also runs in the relay (health, manifest, ownership, credentials, events). The platform then adds the static profile-scope check and recomputes the status from the checks; the relay's own status label is ignored.

## Operate

1. An owner issues a relay credential on **Applications → Connect → Private connector**. The token is shown once; store it in the relay host's secret store.
2. On the relay host (Python 3.12 with `packages/integrations/connectors` installed):
   ```bash
   python -m assureops_connectors.relay --api https://assureops.example.com --token-file /run/secrets/assureops-relay
   ```
   Use `--once` for a single claim (cron or CI).
3. Recent relay tasks and their states are listed on the same page.

## Failure behaviour

| Situation | Result |
|---|---|
| No relay running | Steps end with `relay_timeout` after the per-trial deadline; gate stays incomplete |
| Wrong or revoked relay credential | `403` on claim; nothing is handed out |
| Result without the claim nonce, or a second result | `403 bad_nonce` / `409 not_claimed`; not recorded |
| Result after the deadline | `410 expired`; not recorded |
| Step taken over by another worker meanwhile | the late result is discarded by the step's fencing check |

## Rollback

Remove `execution.mode` from the connection (new connection revision) to return to hosted runners. Revoke relay credentials on the same page. Migration `0011` downgrade drops `relay_tasks`.
