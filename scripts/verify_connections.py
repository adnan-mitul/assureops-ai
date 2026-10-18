"""Verify every application connection that is not yet verified (run after services start).

    python scripts/verify_connections.py [--all]

Uses the same adapter checks as the portal's "Verify connection" action and
prints only check names and statuses, never credentials.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "domain"))

from assureops_domain import connections  # noqa: E402
from assureops_domain.db import platform_session, tenant_session  # noqa: E402
from assureops_domain.models import Application, Workspace  # noqa: E402
from assureops_domain.profile import try_for_application  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="re-verify verified connections too")
    args = parser.parse_args()
    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
    for ws in workspaces:
        with tenant_session(ws) as s:
            for app in s.scalars(select(Application)):
                conn = connections.latest_connection(s, app.id)
                if conn is None or conn.status == "revoked" or (conn.status == "verified" and not args.all):
                    continue
                result = connections.verify(s, app, conn, try_for_application(s, app.id))
                summary = ", ".join(f"{c['id']}={c['status']}" for c in result["checks"])
                print(f"{ws}/{app.id} connection r{conn.revision}: {result['status']} ({summary})")


if __name__ == "__main__":
    main()
