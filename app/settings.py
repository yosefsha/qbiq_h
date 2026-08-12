"""Runtime configuration loaded from environment variables.

Settings are loaded once, at import time, so they are available as soon as
the application module is imported. Every field has a local-development
default so `uvicorn app.main:app` boots with zero environment variables set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _parse_bool(value: str) -> bool:
    """Parses a boolean environment variable value.

    Anything matching one of `_TRUE_VALUES` (case-insensitive) is `True`;
    everything else is `False`.
    """
    return value.strip().lower() in _TRUE_VALUES


def _parse_origins(value: str) -> tuple[str, ...]:
    """Parses a comma-separated list of CORS origins.

    A wildcard origin is rejected: `allow_credentials=True` forbids a
    wildcard origin per ADR-001, since browsers refuse `Access-Control-
    Allow-Origin: *` alongside credentialed requests, which would silently
    break the session cookie.
    """
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    if not origins:
        raise ValueError("ALLOWED_ORIGINS must contain at least one origin.")
    if "*" in origins:
        raise ValueError(
            "ALLOWED_ORIGINS may not contain a wildcard '*': allow_credentials=True "
            "forbids a wildcard origin (see ADR-001-server-owned-cart.md)."
        )
    return origins


@dataclass(frozen=True)
class Settings:
    """Immutable, process-wide application configuration."""

    database_url: str
    redis_url: str
    cookie_secure: bool
    allowed_origins: tuple[str, ...]
    cache_ttl_seconds: int
    session_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Builds `Settings` from environment variables with local defaults."""
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://qbiq:qbiq@localhost:5432/qbiq_h"
            ),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            cookie_secure=_parse_bool(os.environ.get("COOKIE_SECURE", "false")),
            allowed_origins=_parse_origins(
                os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
            ),
            cache_ttl_seconds=int(os.environ.get("CACHE_TTL_SECONDS", "300")),
            session_ttl_seconds=int(os.environ.get("SESSION_TTL_SECONDS", "1800")),
        )


settings: Settings = Settings.from_env()
