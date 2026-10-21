"""Model route lifecycle (development, holdout, shadow, canary, active) with history, and shadow/stage markers on AI results

Rollback: downgrade drops the lifecycle tables and the two ai_results columns. Every phase then
returns to the environment-configured (unmanaged) route, which still needs its qualification record.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('model_route_stages',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('phase', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('stage', sa.String(), nullable=False),
    sa.Column('canary_percent', sa.Integer(), nullable=False),
    sa.Column('qualification_id', sa.String(), nullable=True),
    sa.Column('replaces_id', sa.String(), nullable=True),
    sa.Column('shadow_runs', sa.Integer(), nullable=False),
    sa.Column('shadow_valid', sa.Integer(), nullable=False),
    sa.Column('canary_runs', sa.Integer(), nullable=False),
    sa.Column('canary_valid', sa.Integer(), nullable=False),
    sa.Column('canary_invalid', sa.Integer(), nullable=False),
    sa.Column('changed_by', sa.String(), nullable=False),
    sa.Column('changed_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phase', 'provider', 'model')
    )
    op.create_table('model_route_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('route_id', sa.String(), nullable=False),
    sa.Column('from_stage', sa.String(), nullable=True),
    sa.Column('to_stage', sa.String(), nullable=False),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_model_route_events_route_id', 'model_route_events', ['route_id'])
    for table in ('model_route_stages', 'model_route_events'):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO assureops_app")
    op.add_column('ai_results', sa.Column('route_stage', sa.String(), nullable=True))
    op.add_column('ai_results', sa.Column('shadow_of', sa.String(), nullable=True))


def downgrade():
    op.drop_column('ai_results', 'shadow_of')
    op.drop_column('ai_results', 'route_stage')
    op.drop_index('ix_model_route_events_route_id', table_name='model_route_events')
    op.drop_table('model_route_events')
    op.drop_table('model_route_stages')
