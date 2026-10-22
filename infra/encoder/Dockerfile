# Private encoder service (phase D NLI, phase R embeddings) on CPU. Weights are mounted read-only from the
# pinned snapshot directory (ENCODER_MODELS_DIR) and verified against encoder_pins.json at load time.
FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ENCODER_MODELS_DIR=/models/hf
WORKDIR /app
COPY requirements-models.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
    && pip install -r requirements-models.txt fastapi==0.143.3 starlette==1.8.0 uvicorn==0.34.0 pydantic==2.14.1 \
    && useradd --uid 10001 --no-create-home assureops
COPY packages/ai/assureops_ai/__init__.py packages/ai/assureops_ai/encoder_server.py packages/ai/assureops_ai/encoder_pins.json ./assureops_ai/
USER 10001
EXPOSE 8730
ENTRYPOINT ["python", "-m", "assureops_ai.encoder_server", "--port", "8730"]
