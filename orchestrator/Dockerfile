# syntax=docker/dockerfile:1.7
# Build context: repository root (templates, rules, pipelines and policies ship in the image).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HATCH_BACKUP_DIR=/var/lib/hatch/backups

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home /var/lib/hatch hatch \
 && mkdir -p /var/lib/hatch/backups && chown -R hatch /var/lib/hatch \
 && git config --system --add safe.directory '*'

WORKDIR /app
COPY orchestrator/pyproject.toml orchestrator/
COPY orchestrator/app orchestrator/app
RUN pip install "./orchestrator[postgres]"

COPY templates templates
COPY compliance compliance
COPY pipelines pipelines
COPY policies policies

ENV HATCH_TEMPLATES_DIR=/app/templates \
    HATCH_COMPLIANCE_DIR=/app/compliance/rules \
    HATCH_PIPELINES_DIR=/app/pipelines \
    HATCH_POLICIES_FILE=/app/policies/approval.yaml

USER hatch
WORKDIR /var/lib/hatch
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
