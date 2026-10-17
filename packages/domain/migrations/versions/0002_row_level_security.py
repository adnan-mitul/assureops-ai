"""Row-level security on tenant tables

FORCE is set so the table owner is also subject to the policy; the runtime
role has neither superuser nor BYPASSRLS. A missing context matches nothing.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

# Frozen at this revision; later tables enable RLS in their own migration.
TENANT_TABLES = [
    "applications", "coverage_contracts", "dependency_edges", "releases", "change_sets", "assessments", "job_steps",
    "artifacts", "test_runs", "findings", "finding_reviews", "approvals", "logical_actions", "runtime_events",
    "incidents", "assessment_cases", "evidence_requests", "case_messages", "reports", "review_decisions",
    "report_publications", "readiness_points", "audit_events",
]

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

POLICY = "workspace_id = current_setting('app.workspace_id', true)"


def upgrade():
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({POLICY}) WITH CHECK ({POLICY})")


def downgrade():
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
