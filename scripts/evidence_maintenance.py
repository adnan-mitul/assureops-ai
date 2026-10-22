"""Evidence retention and database/object reconciliation, on demand (the dispatcher also runs it daily).

    python scripts/evidence_maintenance.py            # report only: what would be purged, missing, corrupt or orphaned
    python scripts/evidence_maintenance.py --apply    # tombstone expired evidence that is not on hold
    python scripts/evidence_maintenance.py --apply --delete-orphans   # also remove stored objects with no row (older than 24 h)

Prints counts per workspace only; no evidence content is shown.
"""

import argparse
import json

from sqlalchemy import select

from assureops_domain import retention
from assureops_domain.db import platform_session, tenant_session
from assureops_domain.models import Workspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delete-orphans", action="store_true")
    args = parser.parse_args()
    with platform_session() as s:
        workspaces = [w.id for w in s.scalars(select(Workspace))]
    for ws in workspaces:
        with tenant_session(ws) as s:
            purge = retention.purge_expired(s, actor="evidence_maintenance.py", dry_run=not args.apply)
            check = retention.reconcile(s, ws, delete_orphans=args.apply and args.delete_orphans)
        print(ws, json.dumps({"expired": purge["expired"], "on_hold": len(purge["on_hold"]), "purged": len(purge["purged"]) if args.apply else 0,
                              "would_purge": 0 if args.apply else len(purge["purged"]), "missing": len(check["missing"]),
                              "corrupt": len(check["corrupt"]), "orphans": len(check["orphans"]), "orphans_deleted": len(check["orphans_deleted"])}))


if __name__ == "__main__":
    main()
