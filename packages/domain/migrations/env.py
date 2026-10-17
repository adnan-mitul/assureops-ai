"""Migrations run with the owner role, never the runtime role."""

from alembic import context
from sqlalchemy import create_engine

from assureops_domain import models  # noqa: F401  (registers tables)
from assureops_domain.config import settings
from assureops_domain.db import Base

target_metadata = Base.metadata


def run():
    engine = create_engine(settings().owner_database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
