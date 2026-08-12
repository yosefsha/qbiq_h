"""Tests for `app.main` — app boot, `/health`, and CORS wiring."""

from __future__ import annotations

import importlib

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

_SETTINGS_ENV_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "COOKIE_SECURE",
    "ALLOWED_ORIGINS",
    "CACHE_TTL_SECONDS",
    "SESSION_TTL_SECONDS",
)


def test_health_endpoint_returns_200_ok() -> None:
    import app.main as main_module

    client = TestClient(main_module.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_echoes_request_id_header() -> None:
    import app.main as main_module

    client = TestClient(main_module.app)

    response = client.get("/health")

    assert response.headers.get("X-Request-Id")


def test_app_boots_and_serves_health_with_zero_env_vars_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`uvicorn app.main:app` must boot with no environment variables set."""
    for var in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    import app.main as main_module
    import app.settings as settings_module

    importlib.reload(settings_module)
    importlib.reload(main_module)

    client = TestClient(main_module.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # restore modules to their normal, env-driven state for other tests
    importlib.reload(settings_module)
    importlib.reload(main_module)


def test_cors_is_configured_with_explicit_origins_and_credentials() -> None:
    """allow_credentials=True must never be paired with a wildcard origin."""
    import app.main as main_module

    cors_middleware = next(
        mw for mw in main_module.app.user_middleware if mw.cls is CORSMiddleware
    )

    allow_origins = cors_middleware.kwargs["allow_origins"]
    allow_credentials = cors_middleware.kwargs["allow_credentials"]

    assert allow_credentials is True
    assert "*" not in allow_origins
    assert allow_origins == list(main_module.settings.allowed_origins)
