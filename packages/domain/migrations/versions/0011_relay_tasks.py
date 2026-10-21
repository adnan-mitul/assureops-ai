"""Private connector (relay) tasks: encrypted one-time payloads for customer-run relays (tenant table with RLS)

Rollback: downgrade drops relay_tasks. Connections configured with execution mode "relay" then
have no way to run: their steps fail as runner errors (never as passes) until the mode is removed.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('relay_tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.String(), nullable=False),
    sa.Column('application_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('ref_id', sa.String(), nullable=False),
    sa.Column('fencing_token', sa.Integer(), nullable=True),
    sa.Column('payload_ciphertext', sa.Text(), nullable=True),
    sa.Column('payload_sha256', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('claim_nonce_hash', sa.String(), nullable=True),
    sa.Column('claimed_by', sa.String(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.Column('deadline_at', sa.Float(), nullable=False),
    sa.Column('claimed_at', sa.Float(), nullable=True),
    sa.Column('completed_at', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id', 'application_id'], ['applications.workspace_id', 'applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'id')
    )
    op.create_index('ix_relay_tasks_queue', 'relay_tasks', ['workspace_id', 'application_id', 'status', 'created_at'])
    op.execute("ALTER TABLE relay_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE relay_tasks FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON relay_tasks USING (workspace_id = current_setting('app.workspace_id', true)) "
               "WITH CHECK (workspace_id = current_setting('app.workspace_id', true))")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON relay_tasks TO assureops_app")


def downgrade():
    op.drop_index('ix_relay_tasks_queue', table_name='relay_tasks')
    op.drop_table('relay_tasks')
