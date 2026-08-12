# syntax=docker/dockerfile:1

# Build stage: resolve dependencies into a self-contained virtualenv so the
# runtime image carries no build toolchain and no pip cache.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install -r requirements.txt


# Runtime stage.
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as an unprivileged user; nothing here needs root.
RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY app ./app
# Migrations ship in the runtime image deliberately. `alembic upgrade head` runs
# from this same image — as the `migrate` service locally, and as a one-off task
# before the ECS rolling deploy — so the schema is always migrated by the exact
# build being deployed, never by whatever version a developer's laptop happens
# to have checked out. `alembic/env.py` reuses `app.db.session.engine`, so it
# needs `app` on the path, which WORKDIR already provides.
COPY alembic.ini ./
COPY alembic ./alembic

USER appuser
EXPOSE 8000

# Worker count per CLAUDE.md. ALB and the Compose healthcheck both target /health.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
