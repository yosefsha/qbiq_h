"""Tests for `app.session` — cookie issuance and the Redis session record.

Exercised against a **real Redis** (not a fake), started via
`docker compose up -d redis`. The published port is read from
`TEST_REDIS_URL` / `TEST_REDIS_PORT` so this works whether or not the
default port from `docker-compose.yml` was remapped locally — see the
module docstring below for how the port is resolved.

Every test overrides `app.session.settings` and `app.session.get_redis_client`
directly via `monkeypatch.setattr` rather than reloading `app.settings`
module-wide: this repo's other test modules (`test_main.py`,
`test_settings.py`) reload `app.settings` in place, and doing that here too
would leak a mutated global `Settings` object into whichever of those
modules runs afterwards in the same pytest process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets

import pytest
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.session import SessionId, SessionStore, get_session
from app.settings import Settings

# docker-compose.yml publishes Redis on `${REDIS_PORT:-6379}`. No .env file
# ships in this repo (only .env.example), but a developer may have created
# one to move the port, so `TEST_REDIS_PORT` (or a full `TEST_REDIS_URL`)
# lets that be reflected here instead of assuming the compose default.
_TEST_REDIS_URL = os.environ.get(
    "TEST_REDIS_URL",
    f"redis://localhost:{os.environ.get('TEST_REDIS_PORT', '6379')}/0",
)


def _run(coro):
    """Runs an async call from a sync test body without a pytest-asyncio dep."""
    return asyncio.run(coro)


def _test_settings(*, cookie_secure: bool = False, session_ttl_seconds: int = 1800) -> Settings:
    """Builds a `Settings` instance for a single test, independent of env vars."""
    return Settings(
        database_url="postgresql://unused/unused",
        redis_url=_TEST_REDIS_URL,
        cookie_secure=cookie_secure,
        allowed_origins=("http://localhost",),
        cache_ttl_seconds=300,
        session_ttl_seconds=session_ttl_seconds,
        log_level="INFO",
    )


def _build_app(monkeypatch: pytest.MonkeyPatch, *, settings: Settings) -> FastAPI:
    """A minimal app wiring `get_session` behind `/whoami`, isolated per test.

    `app.session` reads `settings` and `get_redis_client` as names in its own
    module namespace, so patching those two attributes there is enough to
    redirect every test at test-scoped configuration and a fresh client —
    no reload of `app.settings` or `app.redis_client` required.
    """
    import app.session as session_module

    monkeypatch.setattr(session_module, "settings", settings)
    test_client = Redis.from_url(settings.redis_url, decode_responses=True)
    monkeypatch.setattr(session_module, "get_redis_client", lambda: test_client)

    app = FastAPI()
    app.add_middleware(session_module.SessionCookieMiddleware)

    @app.get("/whoami")
    async def whoami(session_id: SessionId = Depends(session_module.get_session)):
        return {"session_id": session_id.value}

    # The routes below exist because a handler returning a dict is the ONLY
    # shape for which FastAPI merges a dependency's sub-response headers. Each
    # of these is a shape a real Cart route takes, and each one silently lost
    # the cookie before the middleware existed.
    @app.get("/direct-response")
    async def direct_response(
        session_id: SessionId = Depends(session_module.get_session),
    ):
        return JSONResponse({"session_id": session_id.value})

    @app.delete("/no-content", status_code=204)
    async def no_content(session_id: SessionId = Depends(session_module.get_session)):
        return Response(status_code=204)

    @app.post("/rejects")
    async def rejects(session_id: SessionId = Depends(session_module.get_session)):
        raise HTTPException(status_code=422, detail="deliberate")

    @app.get("/no-session")
    async def no_session():
        return {"ok": True}

    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # Entered as a context manager: this keeps one event loop alive for every
    # request issued through the client. Without it, `TestClient` tears the
    # loop down after each call, and the async Redis connection opened on the
    # first request outlives it — the second request then fails with
    # "Event loop is closed" instead of reusing the connection.
    app = _build_app(monkeypatch, settings=_test_settings())
    with TestClient(app) as test_client:
        yield test_client


def test_first_request_without_cookie_receives_one(client: TestClient) -> None:
    response = client.get("/whoami")

    assert response.status_code == 200
    issued = response.cookies.get("session_id")
    assert issued
    # secrets.token_urlsafe(32) -> 43 base64url characters, never a UUID's
    # hyphenated, fixed-length-with-dashes shape.
    assert len(issued) == 43
    assert response.json()["session_id"] == issued


def test_second_request_reuses_the_session_and_reissues_the_cookie(
    client: TestClient,
) -> None:
    """The cookie is rewritten on every request, which is what makes the TTL slide.

    This previously asserted that no second `Set-Cookie` was sent. That was
    asserting a bug: `Max-Age` is absolute, so a cookie issued once expires a
    fixed interval after first contact no matter how active the Shopper is.
    A Shopper browsing continuously past SESSION_TTL_SECONDS would have the
    browser drop the cookie while the Redis record was still being refreshed,
    stranding a live Cart.
    """
    first = client.get("/whoami")
    first_session_id = first.json()["session_id"]

    second = client.get("/whoami")

    assert second.json()["session_id"] == first_session_id
    assert "set-cookie" in {k.lower() for k in second.headers.keys()}
    assert f"session_id={first_session_id}" in second.headers["set-cookie"]


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/direct-response", 200),
        ("DELETE", "/no-content", 204),
        ("POST", "/rejects", 422),
    ],
)
def test_cookie_survives_responses_fastapi_does_not_merge_headers_into(
    client: TestClient, method: str, path: str, expected_status: int
) -> None:
    """A first-time Shopper must get a cookie however the handler responded.

    FastAPI merges a dependency's sub-response headers only when the handler
    returns a non-Response value. A handler returning a JSONResponse or a 204,
    or raising, drops them — so a Shopper whose first Cart call was a 422 or a
    DELETE got no cookie, orphaning the Redis record and losing the Cart on
    the next request.
    """
    response = client.request(method, path)

    assert response.status_code == expected_status
    assert response.cookies.get("session_id")


def test_route_without_the_dependency_gets_no_cookie(client: TestClient) -> None:
    """`/health` is hit continuously by the ALB; it must not mint sessions."""
    response = client.get("/no-session")

    assert response.status_code == 200
    assert "set-cookie" not in {k.lower() for k in response.headers.keys()}


def test_session_token_is_never_written_to_the_log_stream(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A Redis outage must not log the bearer token.

    `python-json-logger` promotes every `extra` key to a top-level JSON field,
    so an identifier passed there lands in CloudWatch — with 30-day retention —
    as a still-valid credential, once per request for the whole outage.
    """
    settings = _test_settings()
    unreachable = Redis.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=1, socket_timeout=1
    )
    import app.session as session_module

    monkeypatch.setattr(session_module, "settings", settings)
    monkeypatch.setattr(session_module, "get_redis_client", lambda: unreachable)

    app = FastAPI()
    app.add_middleware(session_module.SessionCookieMiddleware)

    @app.get("/whoami")
    async def whoami(session_id: SessionId = Depends(session_module.get_session)):
        return {"session_id": session_id.value}

    with caplog.at_level(logging.ERROR, logger="app.session"):
        with TestClient(app) as test_client:
            response = test_client.get("/whoami")

    token = response.cookies["session_id"]
    assert token
    for record in caplog.records:
        assert token not in record.getMessage()
        assert token not in str(record.__dict__)


def test_session_id_repr_does_not_leak_the_token() -> None:
    session_id = SessionId("s" * 43)

    assert "s" * 43 not in repr(session_id)


def test_cookie_is_httponly_samesite_lax(client: TestClient) -> None:
    response = client.get("/whoami")

    raw_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in raw_cookie
    assert "SameSite=lax" in raw_cookie
    assert "Path=/" in raw_cookie


def test_cookie_secure_true_when_cookie_secure_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app(monkeypatch, settings=_test_settings(cookie_secure=True))

    with TestClient(app) as secure_client:
        response = secure_client.get("/whoami")

    assert "Secure" in response.headers["set-cookie"]


def test_cookie_secure_absent_when_cookie_secure_false(client: TestClient) -> None:
    """The default: plain HTTP locally must not silently drop the cookie."""
    response = client.get("/whoami")

    assert "Secure" not in response.headers["set-cookie"]


def test_malformed_cookie_is_replaced_rather_than_trusted(
    client: TestClient,
) -> None:
    client.cookies.set("session_id", "not-a-real-token")

    response = client.get("/whoami")

    issued = response.cookies.get("session_id")
    assert issued is not None
    assert issued != "not-a-real-token"
    assert len(issued) == 43


def test_ttl_is_refreshed_on_every_access() -> None:
    """A sliding TTL: touching the record resets it, it doesn't just persist."""
    redis_client = Redis.from_url(_TEST_REDIS_URL, decode_responses=True)
    store = SessionStore(redis_client, ttl_seconds=4)
    session_id = SessionId(secrets.token_urlsafe(32))

    async def scenario() -> tuple[int, int, int]:
        try:
            await store.touch(session_id)
            ttl_after_first_touch = await redis_client.ttl(session_id.redis_key)

            await asyncio.sleep(2)
            ttl_before_second_touch = await redis_client.ttl(session_id.redis_key)

            await store.touch(session_id)
            ttl_after_second_touch = await redis_client.ttl(session_id.redis_key)

            return ttl_after_first_touch, ttl_before_second_touch, ttl_after_second_touch
        finally:
            await redis_client.delete(session_id.redis_key)
            await redis_client.aclose()

    ttl_after_first, ttl_before_second, ttl_after_second = _run(scenario())

    assert 3 <= ttl_after_first <= 4
    # Roughly 2 seconds should have ticked off by the time-of-second-check.
    assert 1 <= ttl_before_second <= 2
    # A fresh touch resets the clock rather than leaving the decayed value.
    assert 3 <= ttl_after_second <= 4


def test_redis_outage_does_not_fail_session_issuance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cookie issuance degrades gracefully when the session store is down.

    Reasoning: cookie issuance and the Redis record are two distinct
    concerns (the issue title itself separates them). A transient Redis
    outage must not turn every request into a 500 just because the Shopper
    is browsing anonymously and hasn't touched their Cart yet — the Cart
    write path (BE-07) is where a still-unreachable Redis has to surface,
    since that is the operation that actually needs the record to exist.
    """
    unreachable_settings = _test_settings()
    app = FastAPI()

    import app.session as session_module

    # The cookie is written by the middleware, not by the dependency — any app
    # mounting `get_session` must register this too.
    app.add_middleware(session_module.SessionCookieMiddleware)

    monkeypatch.setattr(session_module, "settings", unreachable_settings)
    unreachable_client = Redis.from_url(
        "redis://localhost:1/0",
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    monkeypatch.setattr(session_module, "get_redis_client", lambda: unreachable_client)

    @app.get("/whoami")
    async def whoami(session_id: SessionId = Depends(session_module.get_session)):
        return {"session_id": session_id.value}

    with TestClient(app) as down_client:
        response = down_client.get("/whoami")

    assert response.status_code == 200
    assert response.cookies.get("session_id")
