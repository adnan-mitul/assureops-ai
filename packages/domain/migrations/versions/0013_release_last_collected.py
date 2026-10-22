"""Releases record when their identity was last collected, so a redeployed earlier release becomes current again

Rollback: downgrade drops the column; the current release is then again the newest created row,
which misjudges rollbacks to an earlier identical release (the behaviour before 0013).

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('releases', sa.Column('last_collected_at', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('releases', 'last_collected_at')
