# Credential rotation and revocation

| Credential | Where | Rotate or revoke |
|---|---|---|
| Target actor credentials | `connector_secrets` (Fernet with `ASSUREOPS_SECRET_KEY`) | New connection revision with new values; `POST /connection/revoke` revokes all |
| Event source tokens | `event_sources` (hash only) | `POST /applications/{id}/event-sources/{source}/revoke`, then issue a new one |
| CI tokens | `service_credentials` kind `ci` (hash only) | Issue a new one, replace the CI secret, revoke the old row |
| Groq key | server environment or secret manager only | Replace `GROQ_API_KEY`, restart API and workers; never frontend configuration or logs |
| Staff MFA | Keycloak staff realm | Reset the user's OTP credential; required action `CONFIGURE_TOTP` forces re-enrolment |
| Portal sessions | Redis, AES-256-GCM with `SESSION_ENCRYPTION_KEY` | Rotating the key signs everyone out (old sessions fail to decrypt) |
