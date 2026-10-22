"""Seed local development data: identities, memberships, the reference application,
its connection, its reviewed profile (proposed and activated by different people),
its coverage contract and scoped machine credentials.

Customer applications (for example the RefundDesk and DocVault labs) are not
seeded: they are connected through the portal or scripts/connect_application.py.

  python scripts/seed.py            # idempotent seed
  python scripts/seed.py --reset    # drop schema, re-migrate, clear local evidence and ledgers, then seed
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, select, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "domain"))

from assureops_domain import connections, grants  # noqa: E402
from assureops_domain.config import _dev_env, settings  # noqa: E402
from assureops_domain.db import platform_session, tenant_session  # noqa: E402
from assureops_domain.models import (  # noqa: E402
    Application, ApplicationGrant, ApplicationProfile, Connection, EventSource, Membership, ServiceCredential, StaffRole, User, Workspace,
)
from assureops_domain.profile import load_profile_file  # noqa: E402

CUSTOMERS = [
    ("owner@acme.test", "Acme Owner", "acme", "owner"),
    ("dev@acme.test", "Acme Developer", "acme", "developer"),
    ("reviewer@acme.test", "Acme Reviewer", "acme", "reviewer"),
    ("viewer@acme.test", "Acme Viewer", "acme", "viewer"),
    ("dev@globex.test", "Globex Developer", "globex", "developer"),
]
STAFF = [
    ("analyst@assureops.test", "Staff Analyst", ["analyst"]),
    ("reviewer@assureops.test", "Senior Reviewer", ["senior_reviewer"]),
    ("manager@assureops.test", "Case Manager", ["case_manager", "admin"]),
    ("operator@assureops.test", "Platform Operator", ["operator"]),
]


def h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def reset():
    engine = create_engine(settings().owner_database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO assureops_app"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "packages" / "domain", check=True)
    # Local evidence, ledgers and bridge spools; logs and lab actor files are kept.
    for path in [ROOT / "var" / "evidence", ROOT / "var" / "bridge", ROOT / "var" / "tool_ledger.db", ROOT / "var" / "agent_release.txt"]:
        shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
    print("schema reset and migrated; local evidence, ledgers and agent release cleared")


def seed():
    env = _dev_env()
    with platform_session() as s:
        for ws, name in [("acme", "Acme Corp"), ("globex", "Globex Ltd")]:
            if not s.get(Workspace, ws):
                s.add(Workspace(id=ws, name=name))
        s.flush()
        for username, display, ws, role in CUSTOMERS:
            user = s.scalars(select(User).where(User.username == username)).first() or User(username=username, display_name=display, kind="customer")
            s.add(user)
            s.flush()
            if not s.scalars(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == ws)).first():
                s.add(Membership(workspace_id=ws, user_id=user.id, role=role))
        for username, display, roles in STAFF:
            user = s.scalars(select(User).where(User.username == username)).first() or User(username=username, display_name=display, kind="staff")
            s.add(user)
            s.flush()
            for role in roles:
                if not s.scalars(select(StaffRole).where(StaffRole.user_id == user.id, StaffRole.role == role)).first():
                    s.add(StaffRole(user_id=user.id, role=role))
        creds = [("runner", "RUNNER_SERVICE_TOKEN"), ("gateway", "GATEWAY_SERVICE_TOKEN"), ("tool_server", "TOOLS_SERVICE_TOKEN")]
        for kind, key in creds:
            if not s.scalars(select(ServiceCredential).where(ServiceCredential.token_hash == h(env[key]))).first():
                s.add(ServiceCredential(kind=kind, workspace_id="acme", application_id="refund-agent", environment="staging", token_hash=h(env[key])))
        for sid, kind, key in [("refund-agent-1", "agent", "AGENT_SOURCE_TOKEN"), ("refund-tools-1", "tool_server", "TOOLS_SOURCE_TOKEN")]:
            if not s.get(EventSource, sid):
                s.add(EventSource(id=sid, workspace_id="acme", application_id="refund-agent", environment="staging", kind=kind, token_hash=h(env[key])))

    with tenant_session("acme") as s:
        app = s.get(Application, "refund-agent")
        if app is None:
            app = Application(
                id="refund-agent", workspace_id="acme", name="Refund Agent", description="AI agent for customer refund processing",
                purpose="Answers order questions and issues refunds for synthetic accounts", environment="staging",
                mode="enforce_supported_actions", target_url="http://127.0.0.1:8710", tools_url="http://127.0.0.1:8720/mcp",
                authorized_scope={"targets": ["http://127.0.0.1:8710", "http://127.0.0.1:8720/mcp"], "accounts": "synthetic only",
                                  "allowed_actions": ["approved catalog tests", "synthetic refunds"], "authorized_by": "owner@acme.test"},
            )
            s.add(app)
            s.flush()
        with platform_session() as p:  # the reference developer is assigned to the reference application
            dev = p.scalars(select(User).where(User.username == "dev@acme.test")).first()
            if grants.active_grant(s, app.id, dev.id) is None:
                s.add(ApplicationGrant(workspace_id="acme", application_id=app.id, user_id=dev.id, granted_by="seed"))
    with tenant_session("acme") as s:
        app = s.get(Application, "refund-agent")
        if s.scalars(select(Connection).where(Connection.application_id == app.id)).first() is None:
            connections.create_connection(s, app, adapter_id="assureops-mcp-reference", actor="owner@acme.test", config={
                "base_url": "http://127.0.0.1:8710", "tools_url": "http://127.0.0.1:8720/mcp", "environment": "staging",
                "manifest_path": "/manifest", "health_path": "/health", "ownership": {"method": "manifest_application"}})
        if s.scalars(select(ApplicationProfile).where(ApplicationProfile.application_id == app.id)).first() is None:
            row = connections.propose_profile(s, app, load_profile_file("refund-agent"), source="file", actor="dev@acme.test")
            # Reviewed coverage contract and edges are recorded on activation by a different person.
            connections.activate_profile(s, app, row.revision, reviewer="reviewer@acme.test",
                                         note="Reference profile reviewed against the bundled refund agent and its MCP tool listings")
    with tenant_session("globex") as s:
        if not s.get(Application, "support-bot"):
            s.add(Application(id="support-bot", workspace_id="globex", name="Support Bot", description="Globex support assistant (not connected)",
                              purpose="Isolation fixture", environment="staging", mode="observe_only", target_url="http://127.0.0.1:9", tools_url="http://127.0.0.1:9/mcp",
                              authorized_scope={}))
    print("seeded workspaces, identities, reference application, coverage contract and credentials")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.reset:
        reset()
    seed()
