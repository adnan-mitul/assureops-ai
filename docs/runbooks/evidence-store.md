# Evidence store outage or integrity failure

Evidence bytes live in the private S3 bucket (`EVIDENCE_BACKEND=s3`). Every read and availability check verifies the SHA-256 recorded in the database.

* **Outage:** readiness shows the affected controls with `unavailable` evidence; nothing becomes supported. Restore the store; availability recovers on its own (30-second verification cache).
* **Integrity failure (hash mismatch):** treat as tampering. Do not overwrite. Restore the object from the latest backup (`var/backups/<ts>/objects/<sha256>`) or re-run the affected tests. `scripts/backup_restore_check.py` exercises both paths.
* **Bucket policy:** only the platform identity has access; anonymous reads must return 401/403 (`tests/security/test_object_store.py`). Browsers download only through the authorized API route (`/v1/evidence/{run_id}/download`).
