#!/usr/bin/env bash
# Deterministic project checks shared by local development and CI (plan §32.2, integration plan I7).
# Requires the compose services (Postgres, Redis, Keycloak, object store) for integration tests.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=./.venv/Scripts/python; [ -x "$PY" ] || PY=./.venv/bin/python

echo "== migrations at head"
(cd packages/domain && "../../$PY" -m alembic upgrade head)
echo "== python compile"
"$PY" -m compileall -q packages apps/api apps/worker scripts
echo "== secret scan"
bash scripts/verify/secret_scan.sh
echo "== backend tests (security, integration, fault, connectors, AI contract)"
"$PY" -m pytest
echo "== application profiles validate against the permitted template catalogue"
"$PY" scripts/verify/check_profiles.py
echo "== customer and staff portals: types and lint"
npm run typecheck
npm run lint
echo "all checks passed"
