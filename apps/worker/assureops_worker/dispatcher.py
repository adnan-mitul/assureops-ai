"""Transactional outbox dispatcher and reconciler.

Publishes committed dispatch intents to Celery. If Redis loses messages or a
worker dies, the reconciler re-enqueues steps whose lease expired or that were
dispatched but never claimed, from PostgreSQL state.
"""

import time

from sqlalchemy import select

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import CaseIndex, JobStep, Outbox, Workspace, now

from .tasks import finalize_assessment, run_step

UNCLAIMED_AFTER = 300


def dispatch_once() -> int:
    with platform_session() as s:
        rows = s.scalars(select(Outbox).where(Outbox.dispatched_at.is_(None)).order_by(Outbox.id).limit(50).with_for_update(skip_locked=True)).all()
        for row in rows:
            if row.kind == "run_step":
                run_step.delay(row.workspace_id, row.ref_id)
            elif row.kind == "finalize_assessment":
                finalize_assessment.delay(row.workspace_id, row.ref_id)
            row.dispatched_at = now()
        return len(rows)


def reconcile_once():
    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
    for ws in workspaces:
        with tenant_session(ws) as s:
            stuck = s.scalars(select(JobStep).where(
                ((JobStep.status == "running") & (JobStep.lease_expires_at < now()))
                | ((JobStep.status == "pending") & (JobStep.updated_at < now() - UNCLAIMED_AFTER)))).all()
            for step in stuck:
                if step.attempt >= step.max_attempts:
                    step.status, step.last_error = "failed", (step.last_error or "") + " | poison: attempts exhausted"
                    continue
                step.updated_at = now()
                s.add(Outbox(workspace_id=ws, kind="run_step", ref_id=step.id))


def main():
    print("outbox dispatcher running")
    last_reconcile = 0.0
    while True:
        try:
            dispatched = dispatch_once()
            if time.time() - last_reconcile > 15:
                reconcile_once()
                last_reconcile = time.time()
        except Exception as exc:  # keep the loop alive; state stays in PostgreSQL
            print(f"dispatcher error: {exc}")
            dispatched = 0
        time.sleep(0.2 if dispatched else 1.0)


if __name__ == "__main__":
    main()
