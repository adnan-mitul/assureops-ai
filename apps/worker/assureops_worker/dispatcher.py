"""Transactional outbox dispatcher and reconciler.

Publishes committed dispatch intents to Celery. If Redis loses messages or a
worker dies, the reconciler re-enqueues steps whose lease expired or that were
dispatched but never claimed, from PostgreSQL state.
"""

import time

from sqlalchemy import select

from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import CaseIndex, JobStep, Outbox, Workspace, now

from .tasks import ai_phase, fail_poison, finalize_assessment, run_step, source_analysis

UNCLAIMED_AFTER = 300
REDISPATCH_AFTER = 60  # a step whose lease expired is re-dispatched at most once per minute while no worker takes it


def dispatch_once() -> int:
    with platform_session() as s:
        rows = s.scalars(select(Outbox).where(Outbox.dispatched_at.is_(None)).order_by(Outbox.id).limit(50).with_for_update(skip_locked=True)).all()
        for row in rows:
            if row.kind == "run_step":
                run_step.delay(row.workspace_id, row.ref_id)
            elif row.kind == "finalize_assessment":
                finalize_assessment.delay(row.workspace_id, row.ref_id)
            elif row.kind == "ai_phase":
                ai_phase.delay(row.workspace_id, row.ref_id)
            elif row.kind == "source_analysis":
                source_analysis.delay(row.workspace_id, row.ref_id)
            row.dispatched_at = now()
        return len(rows)


def reconcile_once():
    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
    for ws in workspaces:
        poisoned = []
        with tenant_session(ws) as s:
            stuck = s.scalars(select(JobStep).where(
                ((JobStep.status == "running") & (JobStep.lease_expires_at < now()) & (JobStep.updated_at < now() - REDISPATCH_AFTER))
                | ((JobStep.status == "pending") & (JobStep.updated_at < now() - UNCLAIMED_AFTER)))).all()
            for step in stuck:
                if step.attempt >= step.max_attempts:
                    poisoned.append(step.id)
                    continue
                step.updated_at = now()
                s.add(Outbox(workspace_id=ws, kind="run_step", ref_id=step.id))
        for step_id in poisoned:  # terminal state plus finalization, in its own transaction
            fail_poison(ws, step_id)


def deliver_notifications() -> int:
    from assureops_domain import handoffs

    with platform_session() as s:
        return handoffs.deliver_pending(s)


def main():
    print("outbox dispatcher running")
    last_reconcile = 0.0
    while True:
        try:
            dispatched = dispatch_once()
            if time.time() - last_reconcile > 15:
                reconcile_once()
                deliver_notifications()
                last_reconcile = time.time()
        except Exception as exc:  # keep the loop alive; state stays in PostgreSQL
            print(f"dispatcher error: {exc}")
            dispatched = 0
        time.sleep(0.2 if dispatched else 1.0)


if __name__ == "__main__":
    main()
