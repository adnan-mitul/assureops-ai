# Shared platform image; the entrypoint selects the process:
# api | worker | ai-worker | dispatcher | tools | agent (reference target) | migrate (schema, seed, storage check).
FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY profiles ./profiles
COPY scripts/seed.py scripts/storage_check.py ./scripts/
COPY infra/api/entrypoint.sh /usr/local/bin/assureops-entrypoint
RUN pip install --no-cache-dir -r requirements.txt && chmod 0755 /usr/local/bin/assureops-entrypoint \
    && useradd --uid 10001 --no-create-home assureops && mkdir -p /app/var && chown 10001 /app/var
USER 10001
EXPOSE 8700
ENTRYPOINT ["assureops-entrypoint"]
CMD ["api"]
