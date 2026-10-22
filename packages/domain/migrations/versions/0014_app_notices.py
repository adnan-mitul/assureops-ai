"""Application notice board: notices posted by members or by the platform for changes (tenant table with RLS)

Rollback: downgrade drops app_notices. Change and team notices then stop appearing on the board;
notifications already created stay in the inbox and are still delivered.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('app_notices',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.String(), nullable=False),
    sa.Column('application_id', sa.String(), nullable=False),
    sa.Column('author', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id', 'application_id'], ['applications.workspace_id', 'applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'id')
    )
    op.create_index('ix_app_notices_board', 'app_notices', ['workspace_id', 'application_id', 'created_at'])
    op.execute("ALTER TABLE app_notices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_notices FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON app_notices USING (workspace_id = current_setting('app.workspace_id', true)) "
               "WITH CHECK (workspace_id = current_setting('app.workspace_id', true))")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app_notices TO assureops_app")


def downgrade():
    op.drop_index('ix_app_notices_board', table_name='app_notices')
    op.drop_table('app_notices')
