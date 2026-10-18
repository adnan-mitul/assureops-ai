# Shared API/worker image; entrypoint selects the process (api | worker | dispatcher). Built from lockfiles.
FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY profiles ./profiles
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --no-create-home assureops
USER 10001
EXPOSE 8700
ENTRYPOINT ["sh", "-c", "case \"$0\" in api) exec python -m uvicorn assureops_api.main:app --host 0.0.0.0 --port 8700;; worker) exec python -m celery -A assureops_worker.tasks worker -Q assessments --concurrency 2;; dispatcher) exec python -m assureops_worker.dispatcher;; *) echo usage: api, worker or dispatcher; exit 2;; esac"]
CMD ["api"]
