"""Backup and restore drill (integration plan I7/I8): database and evidence objects, without touching live data.

    python scripts/backup_restore_check.py

1. pg_dump of the live database (custom format) into var/backups/<ts>/.
2. Restore into a scratch database and compare row counts of every table.
3. Copy every evidence object to var/backups/<ts>/objects with its SHA-256.
4. Simulate loss of one object in a scratch key, restore it from the backup, and verify the hash.
5. Drop the scratch database.
Prints a pass/fail summary; exits non-zero on any mismatch.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from sqlalchemy import select  # noqa: E402

from assureops_domain import evidence_store  # noqa: E402
from assureops_domain.config import _dev_env  # noqa: E402
from assureops_domain.db import platform_session, tenant_session  # noqa: E402
from assureops_domain.models import Artifact, Workspace  # noqa: E402

CONTAINER = "assureops-postgres-1"
APPEND_ONLY = {"runtime_events", "audit_events", "readiness_points", "outbox", "model_calls", "github_deliveries"}


def psql(sql: str, db: str = "postgres") -> str:
    env = _dev_env()
    out = subprocess.run(["docker", "exec", "-e", f"PGPASSWORD={env['POSTGRES_SUPERUSER_PASSWORD']}", CONTAINER, "psql", "-U", "postgres", "-d", db,
                          "-At", "-c", sql], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main():
    env = _dev_env()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = ROOT / "var" / "backups" / stamp
    (folder / "objects").mkdir(parents=True, exist_ok=True)
    ok = True

    dump = folder / "assureops.dump"
    with dump.open("wb") as fh:
        subprocess.run(["docker", "exec", "-e", f"PGPASSWORD={env['POSTGRES_SUPERUSER_PASSWORD']}", CONTAINER, "pg_dump", "-U", "postgres", "-Fc", "assureops"],
                       stdout=fh, check=True)
    print(f"database dump: {dump.relative_to(ROOT)} ({dump.stat().st_size} bytes)")

    scratch = f"restore_check_{stamp.replace('-', '_')}"
    psql(f"CREATE DATABASE {scratch}")
    try:
        with dump.open("rb") as fh:
            subprocess.run(["docker", "exec", "-i", "-e", f"PGPASSWORD={env['POSTGRES_SUPERUSER_PASSWORD']}", CONTAINER, "pg_restore", "-U", "postgres",
                            "-d", scratch, "--no-owner"], stdin=fh, check=True, capture_output=True)
        tables = psql("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1", scratch).split()
        mismatched = []
        for table in tables:
            # Counts run as the superuser, which bypasses row-level security, so every workspace is compared.
            live = int(psql(f"SELECT count(*) FROM public.{table}", "assureops"))
            restored = int(psql(f"SELECT count(*) FROM public.{table}", scratch))
            if table in APPEND_ONLY and restored <= live:
                continue  # rows appended after the dump's snapshot (heartbeats, audit) are expected
            if live != restored:
                mismatched.append(f"{table}: live {live} restored {restored}")
        print(f"database restore: {len(tables)} tables compared, {len(mismatched)} mismatches")
        for m in mismatched:
            print("  ", m)
        ok &= not mismatched
    finally:
        psql(f"DROP DATABASE IF EXISTS {scratch}")

    rows = []
    with platform_session() as ps:
        workspaces = [w.id for w in ps.scalars(select(Workspace))]
    for ws in workspaces:  # evidence metadata is tenant data: read it through each workspace's context
        with tenant_session(ws) as ts:
            rows += [(a.storage_key, a.sha256) for a in ts.scalars(select(Artifact).where(Artifact.deleted_at.is_(None)))]
    store = evidence_store.storage()
    manifest, copied = {}, 0
    for key, sha in rows:
        data = store.get(key)
        if data is None or hashlib.sha256(data).hexdigest() != sha:
            print(f"  object {key[:40]} missing or damaged in the live store")
            ok = False
            continue
        (folder / "objects" / sha).write_bytes(data)
        manifest[key] = sha
        copied += 1
    (folder / "objects.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"object backup: {copied} of {len(rows)} evidence objects copied with verified hashes")

    if manifest:
        key, sha = next(iter(manifest.items()))
        drill_key = f"restore-drill/{sha}"
        store.put(drill_key, (folder / "objects" / sha).read_bytes())  # restore into a scratch key, never over live evidence
        restored = store.get(drill_key)
        good = restored is not None and hashlib.sha256(restored).hexdigest() == sha
        store.delete(drill_key)
        print(f"object restore drill: {'hash verified' if good else 'FAILED'}")
        ok &= good
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
