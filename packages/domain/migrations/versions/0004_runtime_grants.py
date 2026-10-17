"""Runtime role grants

The runtime role gets DML on application tables only; it cannot alter schema
or touch the migration history.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT USAGE ON SCHEMA public TO assureops_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO assureops_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO assureops_app")
    op.execute("REVOKE ALL ON alembic_version FROM assureops_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO assureops_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO assureops_app")


def downgrade():
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM assureops_app")
