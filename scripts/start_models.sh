#!/usr/bin/env bash
# Starts the private inference services if they are not already running (idempotent).
#   Ollama (generation phases A, B/E, C, F) on 127.0.0.1:8740, models in $OLLAMA_MODELS
#   Encoder service (phases D and R) on 127.0.0.1:8730, pinned weights in $ENCODER_MODELS_DIR
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
[ -x "$PY" ] || PY=./.venv/bin/python
mkdir -p var/logs
OLLAMA_BIN="${OLLAMA_BIN:-$LOCALAPPDATA/Programs/Ollama/ollama.exe}"
if ! curl -s -m 2 http://127.0.0.1:8740/api/version >/dev/null; then
  if [ -x "$OLLAMA_BIN" ] || command -v ollama >/dev/null; then
    [ -x "$OLLAMA_BIN" ] || OLLAMA_BIN=ollama
    OLLAMA_HOST=127.0.0.1:8740 OLLAMA_MODELS="${OLLAMA_MODELS:-D:/AssureOpsModels/ollama}" OLLAMA_MAX_LOADED_MODELS=1 \
      OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=8192 nohup "$OLLAMA_BIN" serve > var/logs/ollama.log 2>&1 &
  else
    echo "ollama not installed: generation phases stay unavailable"
  fi
fi
if ! curl -s -m 2 http://127.0.0.1:8730/info >/dev/null; then
  ENCODER_MODELS_DIR="${ENCODER_MODELS_DIR:-D:/AssureOpsModels/hf}" nohup "$PY" -m assureops_ai.encoder_server --port 8730 > var/logs/encoder.log 2>&1 &
fi
for i in $(seq 1 30); do
  curl -s -m 2 http://127.0.0.1:8740/api/version >/dev/null && curl -s -m 2 http://127.0.0.1:8730/info >/dev/null && break
  sleep 2
done
echo "inference: ollama $(curl -s -m 2 http://127.0.0.1:8740/api/version || echo down), encoder $(curl -s -m 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8730/info)"
