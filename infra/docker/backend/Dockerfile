# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM python:3.12.12-alpine3.23@sha256:2d91681153dd4b8cdb52d4fd34a17b9edbafa4dd3086143cfd4b6c3a84c1acb0 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /build

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install "poetry==2.5.1"

ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv

COPY pyproject.toml poetry.lock README.md ./
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY packages/backend ./packages/backend

RUN poetry install --only main --no-root --no-ansi \
    && poetry build --format wheel --no-ansi \
    && pip install --no-deps dist/financial_analytics-*.whl

FROM python:3.12.12-alpine3.23@sha256:2d91681153dd4b8cdb52d4fd34a17b9edbafa4dd3086143cfd4b6c3a84c1acb0 AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk upgrade --no-cache \
    && addgroup -g 10001 -S app \
    && adduser -u 10001 -S -D -H -G app -s /sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY migrations ./migrations

USER 10001:10001

EXPOSE 8000

CMD ["python", "-m", "financial_analytics_api"]
