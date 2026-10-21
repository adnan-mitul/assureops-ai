"""Retention respects holds and records every deletion; reconciliation finds missing, corrupt and orphaned objects."""

import time
import uuid

from sqlalchemy import select

from assureops_domain import evidence_store, retention
from assureops_domain.db import tenant_session
from assureops_domain.models import Artifact, ArtifactDeletion, AssessmentCase, Finding, Report
from tests.conftest import add_release
from tests.integration.test_evidence_validity import _run

OLD = 400 * 86400


def _artifact(ws: str, age: float = 0) -> str:
    with tenant_session(ws) as s:
        a = evidence_store.put_json(s, ws, {"retention-test": uuid.uuid4().hex})
        a.created_at -= age
        return a.id


def test_expired_evidence_is_tombstoned_unless_a_published_report_or_open_finding_holds_it(workspace):
    release = add_release(workspace, "R1")
    cited, finding_run = _run(workspace, release, "T-C01-01", "passed"), _run(workspace, release, "T-C02-01", "failed")
    with tenant_session(workspace) as s:
        for run in (cited, finding_run):  # the helper's artifacts are placeholders; give these runs real, old stored bytes
            real = evidence_store.put_json(s, workspace, {"run": run.id})
            run_row = s.get(type(run), run.id)
            run_row.artifact_id = real.id
            real.created_at -= OLD
        case = AssessmentCase(workspace_id=workspace, application_id=f"{workspace}-app", title="t", scope_note="n", created_by="t")
        s.add(case)
        s.flush()
        s.add(Report(workspace_id=workspace, application_id=f"{workspace}-app", case_id=case.id, release_id=release.id,
                     snapshot={"evidence": [{"id": cited.id}]}, sha256="x", drafted_by="a", state="published"))
        s.add(Finding(workspace_id=workspace, application_id=f"{workspace}-app", control_id="C02", test_id="T-C02-01", source="test",
                      severity="critical", title="t", description="d", state="open", first_release="R1", last_release="R1",
                      evidence_refs=[{"run_id": finding_run.id}]))
    expired_free = _artifact(workspace, age=OLD)
    fresh = _artifact(workspace)
    with tenant_session(workspace) as s:
        preview = retention.purge_expired(s, dry_run=True)
        assert expired_free in preview["purged"] and fresh not in preview["purged"]
        assert len(preview["on_hold"]) == 2 and s.get(Artifact, expired_free).deleted_at is None  # dry run changes nothing
    with tenant_session(workspace) as s:
        done = retention.purge_expired(s, actor="test", dry_run=False)
        assert set(done["purged"]) == set(preview["purged"])
    with tenant_session(workspace) as s:
        assert s.get(Artifact, expired_free).deleted_at is not None and not evidence_store.available(s.get(Artifact, expired_free))
        assert s.get(Artifact, fresh).deleted_at is None
        history = s.scalars(select(ArtifactDeletion).where(ArtifactDeletion.artifact_id == expired_free)).one()
        assert history.actor == "test" and "retention" in history.reason
        held = [s.get(Artifact, a) for a in preview["on_hold"]]
        assert all(a.deleted_at is None for a in held)
    with tenant_session(workspace) as s:
        for model in (Report, Finding, AssessmentCase):
            for row in s.scalars(select(model)):
                s.delete(row)


def _overwrite(store, key: str, data: bytes):
    if store.name == "s3":
        store.client.put_object(Bucket=store.bucket, Key=key, Body=data)
    else:
        (store.root / key).write_bytes(data)


def test_reconciliation_reports_missing_corrupt_and_orphaned_objects(workspace):
    store = evidence_store.storage()
    missing, corrupt = _artifact(workspace), _artifact(workspace)
    with tenant_session(workspace) as s:
        store.delete(s.get(Artifact, missing).storage_key)
        _overwrite(store, s.get(Artifact, corrupt).storage_key, b"tampered")
    orphan_key = f"{workspace}/orphan-{uuid.uuid4().hex}"
    store.put(orphan_key, b"no row")
    try:
        with tenant_session(workspace) as s:
            first = retention.reconcile(s, workspace, delete_orphans=True)
        assert missing in first["missing"] and corrupt in first["corrupt"]
        assert orphan_key in first["orphans"] and first["orphans_deleted"] == []  # inside the grace period: kept
        with tenant_session(workspace) as s:  # a later sweep past the grace period removes it
            later = retention.reconcile(s, workspace, delete_orphans=True, at=time.time() + 2 * retention.ORPHAN_GRACE_SECONDS)
        assert orphan_key in later["orphans_deleted"] and store.get(orphan_key) is None
    finally:
        store.delete(orphan_key)
