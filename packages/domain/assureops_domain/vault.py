"""Connector secret storage: encrypted at rest, revocable, never returned by the API.

Fernet (AES-128-CBC + HMAC-SHA256) with a deployment key from the secret
manager (`ASSUREOPS_SECRET_KEY`). Decryption happens only when a runner
capsule is built for one authorized step.
"""

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ConnectorSecret, now


class VaultError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _fernet() -> Fernet:
    key = settings().secret_key
    if not key:
        raise VaultError("vault_unconfigured", "ASSUREOPS_SECRET_KEY is not configured; target credentials cannot be stored")
    return Fernet(key.encode())


def fingerprint(value: str) -> str:
    return hmac.new(settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:10]


def store(session: Session, *, workspace_id: str, application_id: str, name: str, value: str, actor: str) -> ConnectorSecret:
    if not value or len(value) > 4096:
        raise VaultError("invalid_secret", "secret must be 1..4096 characters")
    row = ConnectorSecret(workspace_id=workspace_id, application_id=application_id, name=name,
                          ciphertext=_fernet().encrypt(value.encode()).decode(), fingerprint=fingerprint(value), created_by=actor)
    session.add(row)
    session.flush()
    return row


def revoke(session: Session, secret_id: str, actor: str) -> ConnectorSecret:
    row = session.get(ConnectorSecret, secret_id)
    if row is None:
        raise VaultError("not_found", "secret not found")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by = now(), actor
    return row


def reveal(session: Session, secret_id: str) -> str:
    row = session.get(ConnectorSecret, secret_id)
    if row is None or row.revoked_at is not None:
        raise VaultError("revoked", "credential is missing or revoked")
    try:
        return _fernet().decrypt(row.ciphertext.encode()).decode()
    except InvalidToken:
        raise VaultError("undecryptable", "credential cannot be decrypted with the current key")


def describe(row: ConnectorSecret) -> dict:
    return {"id": row.id, "name": row.name, "fingerprint": row.fingerprint, "created_by": row.created_by, "created_at": row.created_at,
            "revoked": row.revoked_at is not None, "revoked_at": row.revoked_at}


def credentials_for(session: Session, application_id: str, actors: dict) -> tuple[dict[str, str], list[str]]:
    """Decrypt the actor credentials a connection references; returns (credentials, problems)."""
    creds, problems = {}, []
    ids = {a: ref.get("secret_id") for a, ref in actors.items()}
    rows = {r.id: r for r in session.scalars(select(ConnectorSecret).where(ConnectorSecret.application_id == application_id))}
    for actor, sid in ids.items():
        if not sid or sid not in rows:
            problems.append(f"{actor}: no credential")
            continue
        try:
            creds[actor] = reveal(session, sid)
        except VaultError as exc:
            problems.append(f"{actor}: {exc.detail}")
    return creds, problems
