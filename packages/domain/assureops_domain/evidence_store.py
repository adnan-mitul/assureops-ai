"""Private, content-addressed evidence storage.

Bytes live under a private directory keyed by generated IDs; the database holds
metadata, hashes and tombstones. Reads recheck the hash and the tombstone.
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Artifact, now

MAX_ARTIFACT_BYTES = 2_000_000


class EvidenceUnavailable(Exception):
    pass


def put_json(session: Session, workspace_id: str, value) -> Artifact:
    data = json.dumps(value, sort_keys=True, indent=2).encode()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("evidence artifact exceeds the size limit")
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalars(select(Artifact).where(Artifact.workspace_id == workspace_id, Artifact.sha256 == digest)).first()
    if existing and existing.deleted_at is None:
        return existing
    folder = settings().evidence_dir / workspace_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / digest
    if not path.exists():
        path.write_bytes(data)
    if existing:  # previously tombstoned; new evidence re-creates the content
        existing.deleted_at = None
        return existing
    artifact = Artifact(workspace_id=workspace_id, sha256=digest, size=len(data), content_type="application/json",
                        storage_key=f"{workspace_id}/{digest}")
    session.add(artifact)
    session.flush()
    return artifact


def read_json(artifact: Artifact):
    if artifact.deleted_at is not None:
        raise EvidenceUnavailable("evidence was deleted")
    path = settings().evidence_dir / artifact.storage_key
    if not path.exists():
        raise EvidenceUnavailable("evidence object is missing from storage")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise EvidenceUnavailable("evidence object failed its integrity check")
    return json.loads(data)


def available(artifact: Artifact | None) -> bool:
    if artifact is None or artifact.deleted_at is not None:
        return False
    return (settings().evidence_dir / artifact.storage_key).exists()


def tombstone(artifact: Artifact):
    """Deletion marks dependent evidence unavailable; it never keeps a supported status alive."""
    artifact.deleted_at = now()
    path = settings().evidence_dir / artifact.storage_key
    if path.exists():
        path.unlink()
