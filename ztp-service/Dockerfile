# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HATCH_ZTP_IMAGE_DIR=/srv/images

RUN useradd --system --uid 10002 ztp && mkdir -p /srv/images && chown ztp /srv/images
WORKDIR /app
COPY pyproject.toml ./
COPY ztp ztp
RUN pip install .

USER ztp
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz')" || exit 1
CMD ["uvicorn", "ztp.main:app", "--host", "0.0.0.0", "--port", "8081", "--proxy-headers"]
