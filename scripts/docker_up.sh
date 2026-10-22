#!/usr/bin/env bash
# Run the whole platform in Docker (infra/compose/full-stack.yml).
#
#   bash scripts/docker_up.sh           # build images, start everything, wait until it answers
#   bash scripts/docker_up.sh --labs    # also start the RefundDesk/DocVault labs (set REFUNDDESK_DIR and DOCVAULT_DIR)
#   bash scripts/docker_up.sh --down    # stop the full stack (data volumes are kept)
#
# Local test values are generated once into the git-ignored dev.env and mounted at run time. The local
# (non-Docker) services must be stopped first: both modes use the same ports.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python; [ -x .venv/Scripts/python ] && PY=.venv/Scripts/python; [ -x .venv/bin/python ] && PY=.venv/bin/python
COMPOSE=(docker compose --env-file infra/compose/dev.env -f infra/compose/full-stack.yml)

if [ "${1:-}" = "--down" ]; then
  "${COMPOSE[@]}" --profile labs down
  exit 0
fi
PROFILE=()
[ "${1:-}" = "--labs" ] && PROFILE=(--profile labs)

# HTTP status of a URL. The body goes through a pipe, not `-o /dev/null`: with MSYS_NO_PATHCONV=1 (Git Bash on
# Windows) the native curl would receive /dev/null untranslated, fail to write it and report every check as failed.
status() { curl -s -m "${2:-3}" -w '\n%{http_code}' "$1" 2>/dev/null | tail -n 1; }

for port in 8700 3700 3710 8740; do
  if [ "$(status "http://127.0.0.1:$port/" 2 || true)" != "000" ] && ! docker ps --format '{{.Names}}' | grep -q '^assureops-hub-1$'; then
    echo "port $port is in use by a local service; stop the local stack first (powershell -File scripts/stop_services.ps1, and quit Ollama)"
    exit 1
  fi
done

[ -f infra/compose/dev.env ] || $PY scripts/init_dev_env.py
$PY scripts/render_realm.py >/dev/null
$PY scripts/render_storage.py >/dev/null
$PY scripts/render_web_env.py >/dev/null

echo "== building images (first run takes a while: Python deps, CPU torch, two Next.js builds)"
"${COMPOSE[@]}" build

echo "== starting storage and identity, then migrating and seeding"
"${COMPOSE[@]}" up -d hub postgres redis keycloak objectstore
"${COMPOSE[@]}" up migrate --exit-code-from migrate

# Prometheus needs a scrape credential stored in the database; render it once the schema exists.
if [ ! -f infra/compose/prometheus/prometheus.netns.rendered.yml ]; then
  $PY scripts/render_monitoring.py
fi

echo "== starting the platform"
"${COMPOSE[@]}" "${PROFILE[@]}" up -d

ready() { for _ in $(seq 1 120); do status "$1" | grep -qE "^($2)$" && return 0; sleep 2; done; echo "not ready: $1"; return 1; }
ready http://127.0.0.1:8700/health 200
ready http://localhost:8780/realms/assureops/.well-known/openid-configuration 200
ready http://127.0.0.1:8710/health 200
ready http://127.0.0.1:8740/api/version 200
ready http://127.0.0.1:8730/info 200
ready http://localhost:3700/api/v1/applications 401
ready http://localhost:3710/api/v1/staff/work-queue 401
echo "AssureOps is running in Docker: customer portal http://localhost:3700, staff portal http://localhost:3710 (stop: bash scripts/docker_up.sh --down)"
