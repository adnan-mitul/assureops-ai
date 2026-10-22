"""Evidence retention and database/object-store reconciliation (per workspace, inside its tenant context).

Retention tombstones evidence older than its `retention_days`, except evidence on hold:
cited by a published or superseded report (the frozen report must stay verifiable)
or by an open finding. Runtime events are database rows and are not purged here. Every tombstone is recorded in the
deletion history, and dependent evidence immediately becomes unavailable, never support.

Reconciliation compares artifact rows with stored objects: rows whose bytes are missing
or fail their hash are reported (they already read as unavailable); objects without a row
are orphans, deleted only when older than the grace period and only when asked.
"""

import hashlib
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence_store
from .models import Artifact, Finding, Report, TestRun, now

ORPHAN_GRACE_SECONDS = 24 * 3600  # an upload can land in the store a moment before its row commits


def _held(session: Session) -> set[str]:
    run_ids: set[str] = set()
    for r in session.scalars(select(Report).where(Report.state.in_(["published", "superseded"]))):
        run_ids |= {e.get("id") for e in (r.snapshot or {}).get("evidence", []) if e.get("id")}
    for f in session.scalars(select(Finding).where(Finding.state != "resolved")):
        run_ids |= {ref.get("run_id") for ref in (f.evidence_refs or []) if isinstance(ref, dict) and ref.get("run_id")}
    return {run.artifact_id for run in session.scalars(select(TestRun).where(TestRun.id.in_(run_ids)))} if run_ids else set()


def purge_expired(session: Session, *, actor: str = "retention", dry_run: bool = True, at: float | None = None) -> dict:
    t = at or now()
    held = _held(session)
    expired = [a for a in session.scalars(select(Artifact).where(Artifact.deleted_at.is_(None)))
               if a.created_at + a.retention_days * 86400 < t]
    on_hold = [a for a in expired if a.id in held]
    purged = [a for a in expired if a.id not in held]
    if not dry_run:
        for a in purged:
            evidence_store.tombstone(session, a, actor=actor, reason=f"retention: older than {a.retention_days} days")
    return {"expired": len(expired), "on_hold": [a.id for a in on_hold], "purged": [a.id for a in purged], "dry_run": dry_run}


def reconcile(session: Session, workspace_id: str, *, delete_orphans: bool = False, at: float | None = None) -> dict:
    t = at or time.time()
    store = evidence_store.storage()
    rows = session.scalars(select(Artifact)).all()
    by_key = {a.storage_key: a for a in rows}
    missing, corrupt = [], []
    for a in rows:
        if a.deleted_at is not None:
            continue
        data = store.get(a.storage_key)
        if data is None:
            missing.append(a.id)
        elif hashlib.sha256(data).hexdigest() != a.sha256:
            corrupt.append(a.id)
    orphans, removed = [], []
    for key in store.keys(f"{workspace_id}/"):
        row = by_key.get(key)
        if row is None or row.deleted_at is not None:
            orphans.append(key)
            modified = store.modified_at(key)
            old_enough = modified is not None and t - modified > ORPHAN_GRACE_SECONDS  # unknown age: keep it
            if delete_orphans and old_enough:
                store.delete(key)
                removed.append(key)
    return {"artifacts": len(rows), "missing": missing, "corrupt": corrupt, "orphans": orphans, "orphans_deleted": removed}
