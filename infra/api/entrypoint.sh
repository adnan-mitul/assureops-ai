#!/bin/sh
# Selects the process this image runs. Configuration comes from the environment or a mounted
# dev.env; no secret is ever baked into the image.
set -e
case "$1" in
  api) exec python -m uvicorn assureops_api.main:app --host 0.0.0.0 --port "${API_PORT:-8700}" ;;
  worker) exec python -m celery -A assureops_worker.tasks worker -Q assessments --concurrency "${WORKER_CONCURRENCY:-2}" -n assess@%h --loglevel=WARNING ;;
  ai-worker) exec python -m celery -A assureops_worker.tasks worker --pool=solo -Q ai,analysis -n models@%h --loglevel=WARNING ;;
  dispatcher) exec python -m assureops_worker.dispatcher ;;
  tools) exec python -m assureops_mcp.tool_server ;;
  agent) exec python -m uvicorn assureops_mcp.agent.app:app --host 0.0.0.0 --port 8710 ;;
  migrate)
    # schema to head, idempotent seed (identities, reference application, credentials), then an object store round trip
    (cd packages/domain && python -m alembic upgrade head)
    python scripts/seed.py
    exec python scripts/storage_check.py ;;
  *) echo "usage: api | worker | ai-worker | dispatcher | tools | agent | migrate"; exit 2 ;;
esac
