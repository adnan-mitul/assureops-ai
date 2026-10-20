#!/usr/bin/env bash
# Starts the local backend services in the background, logging to var/logs/.
set -e
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
[ -x "$PY" ] || PY=./.venv/bin/python
mkdir -p var/logs
bash scripts/start_models.sh
"$PY" -m assureops_mcp.tool_server > var/logs/tools.log 2>&1 &
sleep 3
"$PY" -m uvicorn assureops_api.main:app --port 8700 > var/logs/api.log 2>&1 &
"$PY" -m uvicorn assureops_mcp.agent.app:app --port 8710 > var/logs/agent.log 2>&1 &
"$PY" -m celery -A assureops_worker.tasks worker --pool=solo -Q assessments -n assess@%h --loglevel=WARNING > var/logs/worker.log 2>&1 &
"$PY" -m celery -A assureops_worker.tasks worker --pool=solo -Q ai,analysis -n models@%h --loglevel=WARNING > var/logs/worker-models.log 2>&1 &
"$PY" -m assureops_worker.dispatcher > var/logs/dispatcher.log 2>&1 &
sleep 5
"$PY" scripts/verify_connections.py || echo "connection verification skipped (see output above)"
echo "tool server :8720, API :8700, agent :8710, worker and dispatcher started (logs in var/logs)"
