"""Database engine and session factory.

Built once, at import time, from `settings.database_url` so the same code
runs unchanged against the local Docker Compose Postgres and the production
RDS instance (ADR-003) — only the environment variable differs.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import settings


def _psycopg_dialect_url(database_url: str) -> str:
    """Qualifies a bare `postgresql://` URL with the `psycopg` (v3) driver.

    `settings.database_url` intentionally carries no driver qualifier, since
    it also has to work as a plain connection string for tools like `psql`.
    SQLAlchemy's default driver for the bare `postgresql://` scheme is
    `psycopg2`, but this project pins `psycopg[binary]` (v3) in
    requirements.txt instead, so the scheme is qualified here before the
    engine is built.
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


engine: Engine = create_engine(
    _psycopg_dialect_url(settings.database_url), pool_pre_ping=True, future=True
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)
