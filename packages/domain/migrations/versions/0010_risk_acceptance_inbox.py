"""Release-bound risk acceptances (tenant table with RLS) and an in-app read flag on notifications

Rollback: downgrade drops risk_acceptances (every accepted risk stops affecting the gate,
so gates can only get stricter) and the notifications.read_at column (inbox items show as unread).

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('risk_acceptances',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.String(), nullable=False),
    sa.Column('application_id', sa.String(), nullable=False),
    sa.Column('release_id', sa.String(), nullable=False),
    sa.Column('control_id', sa.String(), nullable=False),
    sa.Column('severity', sa.String(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('compensating_controls', sa.Text(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('requested_by', sa.String(), nullable=False),
    sa.Column('decided_by', sa.String(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.Float(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('decided_at', sa.Float(), nullable=True),
    sa.Column('revoked_by', sa.String(), nullable=True),
    sa.Column('revoked_at', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id', 'application_id'], ['applications.workspace_id', 'applications.id'], ),
    sa.ForeignKeyConstraint(['workspace_id', 'release_id'], ['releases.workspace_id', 'releases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'id')
    )
    op.execute("ALTER TABLE risk_acceptances ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE risk_acceptances FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON risk_acceptances USING (workspace_id = current_setting('app.workspace_id', true)) "
               "WITH CHECK (workspace_id = current_setting('app.workspace_id', true))")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON risk_acceptances TO assureops_app")
    op.add_column('notifications', sa.Column('read_at', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('notifications', 'read_at')
    op.drop_table('risk_acceptances')
