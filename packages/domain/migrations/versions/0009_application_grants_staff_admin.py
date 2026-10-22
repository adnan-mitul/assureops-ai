"""Application-scoped developer grants (tenant table with RLS) and staff role grant history

Existing active developers keep their current reach: the upgrade grants each of them every
application of their workspace, recorded as granted_by "migration-0009". New developers get
applications only through an owner's explicit assignment.

Rollback: downgrade drops application_grants and the staff role history columns; developers
then write to every application of their workspace again, as before 0009.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('application_grants',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('workspace_id', sa.String(), nullable=False),
    sa.Column('application_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('granted_by', sa.String(), nullable=False),
    sa.Column('granted_at', sa.Float(), nullable=False),
    sa.Column('expires_at', sa.Float(), nullable=True),
    sa.Column('revoked_by', sa.String(), nullable=True),
    sa.Column('revoked_at', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id', 'application_id'], ['applications.workspace_id', 'applications.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'id')
    )
    op.create_index('ix_application_grants_lookup', 'application_grants', ['workspace_id', 'application_id', 'user_id'])
    op.execute("ALTER TABLE application_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE application_grants FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON application_grants USING (workspace_id = current_setting('app.workspace_id', true)) "
               "WITH CHECK (workspace_id = current_setting('app.workspace_id', true))")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON application_grants TO assureops_app")

    # Backfill per workspace: applications are behind forced RLS, so set the tenant context for each one.
    bind = op.get_bind()
    workspaces = [r[0] for r in bind.execute(sa.text("SELECT DISTINCT workspace_id FROM memberships WHERE role = 'developer' AND active"))]
    for ws in workspaces:
        bind.execute(sa.text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": ws})
        bind.execute(sa.text(
            "INSERT INTO application_grants (id, workspace_id, application_id, user_id, granted_by, granted_at) "
            "SELECT 'agr_' || substr(md5(a.id || m.user_id), 1, 16), a.workspace_id, a.id, m.user_id, 'migration-0009', extract(epoch from now()) "
            "FROM applications a JOIN memberships m ON m.workspace_id = a.workspace_id AND m.role = 'developer' AND m.active "
            "WHERE a.workspace_id = :ws"), {"ws": ws})
    bind.execute(sa.text("SELECT set_config('app.workspace_id', '', true)"))

    for column in ('granted_by', 'revoked_by'):
        op.add_column('staff_roles', sa.Column(column, sa.String(), nullable=True))
    for column in ('granted_at', 'revoked_at'):
        op.add_column('staff_roles', sa.Column(column, sa.Float(), nullable=True))


def downgrade():
    for column in ('revoked_at', 'granted_at', 'revoked_by', 'granted_by'):
        op.drop_column('staff_roles', column)
    op.drop_index('ix_application_grants_lookup', table_name='application_grants')
    op.drop_table('application_grants')
