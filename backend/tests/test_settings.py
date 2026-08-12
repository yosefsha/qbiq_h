"""Tests for `app.settings`."""

from __future__ import annotations

import pytest

from app.settings import Settings

_ENV_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "COOKIE_SECURE",
    "ALLOWED_ORIGINS",
    "CACHE_TTL_SECONDS",
    "SESSION_TTL_SECONDS",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removes every setting-related env var so defaults are exercised."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_settings_load_with_zero_env_vars_set(clean_env: None) -> None:
    """The app must boot with no environment configured at all."""
    settings = Settings.from_env()

    assert settings.database_url
    assert settings.redis_url
    assert settings.cache_ttl_seconds > 0
    assert settings.session_ttl_seconds > 0
    assert settings.allowed_origins


def test_default_cookie_secure_is_false_for_local_http_compose(
    clean_env: None,
) -> None:
    """A plain-HTTP local Compose run must not silently drop cookies."""
    settings = Settings.from_env()

    assert settings.cookie_secure is False


def test_default_allowed_origins_has_no_wildcard(clean_env: None) -> None:
    settings = Settings.from_env()

    assert "*" not in settings.allowed_origins


@pytest.mark.parametrize("raw_value", ["true", "True", "1", "yes", "on"])
def test_cookie_secure_parses_truthy_values(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    monkeypatch.setenv("COOKIE_SECURE", raw_value)

    settings = Settings.from_env()

    assert settings.cookie_secure is True


@pytest.mark.parametrize("raw_value", ["false", "False", "0", "no", "off", ""])
def test_cookie_secure_parses_falsy_values(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    monkeypatch.setenv("COOKIE_SECURE", raw_value)

    settings = Settings.from_env()

    assert settings.cookie_secure is False


def test_allowed_origins_parses_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "https://shop.example.com, https://admin.example.com"
    )

    settings = Settings.from_env()

    assert settings.allowed_origins == (
        "https://shop.example.com",
        "https://admin.example.com",
    )


def test_allowed_origins_rejects_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_credentials=True forbids a wildcard origin (ADR-001)."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    with pytest.raises(ValueError, match="wildcard"):
        Settings.from_env()


def test_allowed_origins_rejects_wildcard_mixed_with_explicit_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://shop.example.com,*")

    with pytest.raises(ValueError, match="wildcard"):
        Settings.from_env()


def test_allowed_origins_rejects_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "")

    with pytest.raises(ValueError):
        Settings.from_env()


def test_ttl_settings_are_parsed_as_integers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "900")

    settings = Settings.from_env()

    assert settings.cache_ttl_seconds == 60
    assert settings.session_ttl_seconds == 900


def test_settings_is_frozen(clean_env: None) -> None:
    settings = Settings.from_env()

    with pytest.raises(Exception):
        settings.cookie_secure = True  # type: ignore[misc]
