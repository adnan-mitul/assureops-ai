"""Database access with transaction-scoped tenant context for row-level security.

The runtime connects as `assureops_app`, which is not a superuser and has no
BYPASSRLS. Every transaction that touches tenant-owned tables first sets
`app.workspace_id`; policies hide all other workspaces' rows.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings().app_database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection):
    """Re-apply the tenant context at the start of every transaction in a tenant session."""
    workspace_id = session.info.get("workspace_id")
    if workspace_id:
        connection.execute(text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": workspace_id})


class Base(DeclarativeBase):
    pass


@contextmanager
def platform_session():
    """Session without tenant context: only platform tables are visible."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def tenant_session(workspace_id: str):
    """Session whose transaction can only see one workspace's tenant rows."""
    session = SessionLocal()
    session.info["workspace_id"] = workspace_id
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def set_tenant(session: Session, workspace_id: str):
    """Bind an existing session to a workspace; applies from its next transaction.

    set_config(..., true) is transaction-local, equivalent to SET LOCAL, so the
    context never leaks to the next user of a pooled connection.
    """
    session.info["workspace_id"] = workspace_id
    if session.in_transaction():
        session.execute(text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": workspace_id})
