"""Private, content-addressed evidence storage.

Bytes live in a private object store (S3-compatible bucket, or a local
directory for isolated development) keyed by workspace and content hash; the
database holds metadata, hashes, tombstones and deletion history. Every read
and every availability check verifies the stored bytes against the recorded
SHA-256, so tampered or missing evidence becomes `unavailable`, never support.
"""

import hashlib
import json
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Artifact, ArtifactDeletion, now

MAX_ARTIFACT_BYTES = 2_000_000
VERIFY_CACHE_SECONDS = 30


class EvidenceUnavailable(Exception):
    pass


class FileStorage:
    name = "fs"

    def __init__(self, root):
        self.root = root

    def put(self, key: str, data: bytes):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.exists() else None

    def version(self, key: str):
        path = self.root / key
        if not path.exists():
            return None
        st = path.stat()
        return (st.st_size, st.st_mtime_ns)

    def delete(self, key: str):
        path = self.root / key
        if path.exists():
            path.unlink()


class S3Storage:
    """Private bucket; objects are never public and are only served through authorized API routes."""

    name = "s3"

    def __init__(self, cfg):
        import boto3
        from botocore.config import Config

        self.bucket = cfg.s3_bucket
        self.client = boto3.client("s3", endpoint_url=cfg.s3_endpoint, aws_access_key_id=cfg.s3_access_key,
                                   aws_secret_access_key=cfg.s3_secret_key, region_name="us-east-1",
                                   config=Config(signature_version="s3v4", retries={"max_attempts": 3},
                                                 connect_timeout=3, read_timeout=10, s3={"addressing_style": "path"}))
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/json",
                               ChecksumAlgorithm="SHA256")

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception as exc:  # store outage is unavailability, not absence of a defect
            raise EvidenceUnavailable(f"evidence store unavailable: {exc.__class__.__name__}")

    def version(self, key: str):
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return None
        return (head["ContentLength"], head.get("ETag"))

    def delete(self, key: str):
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage = None
_lock = threading.Lock()
_verified: dict[str, tuple[object, float]] = {}


def storage():
    global _storage
    with _lock:
        if _storage is None:
            cfg = settings()
            _storage = S3Storage(cfg) if cfg.evidence_backend == "s3" else FileStorage(cfg.evidence_dir)
        return _storage


def put_json(session: Session, workspace_id: str, value) -> Artifact:
    data = json.dumps(value, sort_keys=True, indent=2).encode()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("evidence artifact exceeds the size limit")
    digest = hashlib.sha256(data).hexdigest()
    key = f"{workspace_id}/{digest}"
    existing = session.scalars(select(Artifact).where(Artifact.workspace_id == workspace_id, Artifact.sha256 == digest)).first()
    if existing and existing.deleted_at is None and _verify(existing):
        return existing
    storage().put(key, data)
    _verified.pop(key, None)
    if existing:  # previously tombstoned or damaged; new identical evidence re-creates the content
        existing.deleted_at = None
        existing.storage_key = key
        return existing
    artifact = Artifact(workspace_id=workspace_id, sha256=digest, size=len(data), content_type="application/json", storage_key=key)
    session.add(artifact)
    session.flush()
    return artifact


def put_bytes(session: Session, workspace_id: str, data: bytes, content_type: str, limit: int = 8_000_000) -> Artifact:
    """Content-addressed private object for non-JSON inputs (for example an authorized source snapshot)."""
    if len(data) > limit:
        raise ValueError("object exceeds the size limit")
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalars(select(Artifact).where(Artifact.workspace_id == workspace_id, Artifact.sha256 == digest)).first()
    if existing and existing.deleted_at is None and _verify(existing):
        return existing
    key = f"{workspace_id}/{digest}"
    store = storage()
    if isinstance(store, S3Storage):
        store.client.put_object(Bucket=store.bucket, Key=key, Body=data, ContentType=content_type, ChecksumAlgorithm="SHA256")
    else:
        store.put(key, data)
    _verified.pop(key, None)
    if existing:
        existing.deleted_at, existing.storage_key = None, key
        return existing
    artifact = Artifact(workspace_id=workspace_id, sha256=digest, size=len(data), content_type=content_type, storage_key=key)
    session.add(artifact)
    session.flush()
    return artifact


def read_bytes(artifact: Artifact) -> bytes:
    if artifact.deleted_at is not None:
        raise EvidenceUnavailable("evidence was deleted")
    data = storage().get(artifact.storage_key)
    if data is None:
        raise EvidenceUnavailable("evidence object is missing from storage")
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise EvidenceUnavailable("evidence object failed its integrity check")
    return data


def read_json(artifact: Artifact):
    return json.loads(read_bytes(artifact))


def _verify(artifact: Artifact) -> bool:
    """Hash check with a short cache keyed on the object's size/version, so edits are noticed."""
    store = storage()
    version = store.version(artifact.storage_key)
    if version is None:
        return False
    cached = _verified.get(artifact.storage_key)
    if cached and cached[0] == version and time.time() - cached[1] < VERIFY_CACHE_SECONDS:
        return True
    try:
        read_bytes(artifact)
    except EvidenceUnavailable:
        _verified.pop(artifact.storage_key, None)
        return False
    _verified[artifact.storage_key] = (version, time.time())
    return True


def available(artifact: Artifact | None) -> bool:
    if artifact is None or artifact.deleted_at is not None:
        return False
    return _verify(artifact)


def tombstone(session: Session, artifact: Artifact, *, actor: str, reason: str):
    """Deletion marks dependent evidence unavailable and is recorded; it never keeps a supported status alive."""
    if not reason.strip():
        raise ValueError("a deletion reason is required")
    artifact.deleted_at = now()
    session.add(ArtifactDeletion(workspace_id=artifact.workspace_id, artifact_id=artifact.id, sha256=artifact.sha256, actor=actor, reason=reason))
    storage().delete(artifact.storage_key)
    _verified.pop(artifact.storage_key, None)


def deletion_history(session: Session) -> list[dict]:
    return [{"artifact_id": d.artifact_id, "sha256": d.sha256, "actor": d.actor, "reason": d.reason, "at": d.created_at}
            for d in session.scalars(select(ArtifactDeletion).order_by(ArtifactDeletion.created_at.desc()))]
