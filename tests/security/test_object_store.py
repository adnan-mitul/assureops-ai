"""Private S3 evidence storage: integrity on read, tamper detection, no anonymous access, deletion history."""

import httpx
import pytest

from assureops_domain import evidence_store
from assureops_domain.config import settings
from assureops_domain.db import tenant_session

pytestmark = pytest.mark.skipif(settings().evidence_backend != "s3", reason="object store backend not configured")


def test_tampered_object_becomes_unavailable_and_deletion_is_recorded(workspace):
    with tenant_session(workspace) as s:
        art = evidence_store.put_json(s, workspace, {"evidence": "original", "ws": workspace})
        assert evidence_store.available(art) and evidence_store.read_json(art)["evidence"] == "original"
        store = evidence_store.storage()
        store.client.put_object(Bucket=store.bucket, Key=art.storage_key, Body=b'{"evidence": "edited"}')
        evidence_store._verified.clear()
        assert not evidence_store.available(art)
        with pytest.raises(evidence_store.EvidenceUnavailable):
            evidence_store.read_json(art)
        evidence_store.tombstone(s, art, actor="owner@acme.test", reason="test erasure")
        assert evidence_store.deletion_history(s)[0]["reason"] == "test erasure"
        assert store.get(art.storage_key) is None


def test_bucket_refuses_anonymous_reads(workspace):
    with tenant_session(workspace) as s:
        art = evidence_store.put_json(s, workspace, {"private": True, "ws": workspace})
    cfg = settings()
    res = httpx.get(f"{cfg.s3_endpoint}/{cfg.s3_bucket}/{art.storage_key}", timeout=5)
    assert res.status_code in (401, 403)
