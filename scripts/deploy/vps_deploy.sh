#!/usr/bin/env bash
# Deploy or roll back the full Docker stack on a single Linux VPS using prebuilt GHCR images.
#
#   bash scripts/deploy/vps_deploy.sh --sha <commit-sha> --registry ghcr.io/<owner>/assureops
#   bash scripts/deploy/vps_deploy.sh --rollback
#   bash scripts/deploy/vps_deploy.sh --local-build
#
# Keeps git-ignored infra/compose/dev.env, apps/*/.env.local, rendered configs, and data volumes intact.
set -euo pipefail

cd "$(dirname "$0")/../.."

PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3

COMPOSE=(docker compose --env-file infra/compose/dev.env -f infra/compose/full-stack.yml)
IMAGES=(app encoder customer-web staff-web)

SHA=""
REGISTRY_PREFIX=""
ROLLBACK=false
LOCAL_BUILD=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --sha) SHA="${2:?missing --sha value}"; shift 2 ;;
    --registry) REGISTRY_PREFIX="${2:?missing --registry value}"; shift 2 ;;
    --rollback) ROLLBACK=true; shift ;;
    --local-build) LOCAL_BUILD=true; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ ! -f infra/compose/dev.env ]; then
  echo "infra/compose/dev.env not found; run initial VPS setup before deploying" >&2
  exit 1
fi

status() { curl -s -m "${2:-3}" -w '\n%{http_code}' "$1" 2>/dev/null | tail -n 1; }
ready() {
  for _ in $(seq 1 120); do
    status "$1" | grep -qE "^($2)$" && return 0
    sleep 2
  done
  echo "health check failed: $1 (expected $2)" >&2
  return 1
}

verify_stack() {
  ready http://127.0.0.1:8700/health 200
  ready http://localhost:8780/realms/assureops/.well-known/openid-configuration 200
  ready http://127.0.0.1:8710/health 200
  ready http://127.0.0.1:8740/api/version 200
  ready http://127.0.0.1:8730/info 200
  ready http://localhost:3700/api/v1/applications 401
  ready http://localhost:3710/api/v1/staff/work-queue 401
}

snapshot_rollback_tags() {
  for img in "${IMAGES[@]}"; do
    if docker image inspect "assureops-${img}:local" >/dev/null 2>&1; then
      docker tag "assureops-${img}:local" "assureops-${img}:rollback"
    fi
  done
}

restore_rollback_tags() {
  for img in "${IMAGES[@]}"; do
    if ! docker image inspect "assureops-${img}:rollback" >/dev/null 2>&1; then
      echo "no rollback image found for assureops-${img}" >&2
      return 1
    fi
  done
  for img in "${IMAGES[@]}"; do
    docker tag "assureops-${img}:rollback" "assureops-${img}:local"
  done
}

if [ "$ROLLBACK" = true ]; then
  echo "== restoring previous :rollback images"
  restore_rollback_tags
  "${COMPOSE[@]}" up -d --no-build --remove-orphans
  verify_stack
  echo "== rollback succeeded"
  exit 0
fi

if [ -n "$SHA" ]; then
  echo "== updating repository to $SHA"
  git fetch origin --prune
  git checkout -f "$SHA"
fi

echo "== rendering configuration from infra/compose/dev.env"
"$PY" scripts/render_realm.py >/dev/null
"$PY" scripts/render_storage.py >/dev/null
"$PY" scripts/render_web_env.py >/dev/null

snapshot_rollback_tags

if [ "$LOCAL_BUILD" = true ]; then
  echo "== building images sequentially (low-RAM mode)"
  for svc in migrate encoder customer-web staff-web; do
    "${COMPOSE[@]}" build "$svc"
  done
else
  : "${REGISTRY_PREFIX:?--registry is required unless --local-build or --rollback is set}"
  : "${SHA:?--sha is required unless --local-build or --rollback is set}"
  echo "== pulling prebuilt images for $SHA"
  if [ -n "${GHCR_TOKEN:-}" ] && [ -n "${GHCR_USER:-}" ]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
  fi
  for img in "${IMAGES[@]}"; do
    docker pull "${REGISTRY_PREFIX}-${img}:${SHA}"
    docker tag "${REGISTRY_PREFIX}-${img}:${SHA}" "assureops-${img}:local"
  done
fi

echo "== starting core storage/identity and running migrations"
"${COMPOSE[@]}" up -d hub postgres redis keycloak objectstore
"${COMPOSE[@]}" up migrate --exit-code-from migrate

if [ ! -f infra/compose/prometheus/prometheus.netns.rendered.yml ]; then
  "$PY" scripts/render_monitoring.py
fi

echo "== updating running services"
"${COMPOSE[@]}" up -d --no-build --remove-orphans

if ! verify_stack; then
  echo "== deploy verification failed; attempting automatic rollback" >&2
  if restore_rollback_tags; then
    "${COMPOSE[@]}" up -d --no-build --remove-orphans
    verify_stack || true
  fi
  exit 1
fi

docker image prune -f >/dev/null 2>&1 || true
echo "== deployment succeeded (${SHA:-local})"
