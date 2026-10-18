# Disposable test runner: one capsule on stdin, one JSON result on stdout, then the container is removed.
# No platform credentials, database, broker or storage access exist inside this image or its environment.
FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir httpx==0.28.1 jsonschema==4.26.0
# Only the pure matcher module from the domain package and the connectors package are installed
# (into site-packages, because the entrypoint runs in isolated mode and ignores the working directory).
ARG SITE=/usr/local/lib/python3.12/site-packages
COPY packages/domain/assureops_domain/__init__.py packages/domain/assureops_domain/matchers.py ${SITE}/assureops_domain/
COPY packages/integrations/connectors/assureops_connectors ${SITE}/assureops_connectors
RUN python -c "import assureops_connectors.sandbox, assureops_domain.matchers"
WORKDIR /tmp
USER 65534:65534
ENTRYPOINT ["python", "-I", "-m", "assureops_connectors.sandbox"]
