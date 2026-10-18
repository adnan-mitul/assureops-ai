# Backup, restore and deletion

* **Drill:** `python scripts/backup_restore_check.py` dumps PostgreSQL, restores into a scratch database and compares every table (append-only tables may only grow), copies every evidence object with a verified hash and restores one into a scratch key. Run it before each release and after storage changes.
* **Real restore:** stop the API and workers, `pg_restore --clean` the dump, copy objects back by key (`<workspace>/<sha256>`), start services, run `scripts/verify_connections.py`.
* **Customer erasure:** an owner calls `POST /v1/evidence/{run_id}/delete` with a reason. The bytes are removed, the run stays as metadata, the deletion is recorded (`GET /v1/evidence-deletions`), and affected controls become `unavailable` until re-tested. Published reports keep their hash; the current-status view shows the change.
* **Migrations:** expand, then contract. CI runs upgrade, downgrade one step, upgrade on every change.
