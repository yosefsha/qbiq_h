"""Anonymous session identification (implements ADR-001, bounded by ADR-002).

`get_session` is the FastAPI dependency every Cart route depends on. It
reads the `session_id` cookie, minting one via `secrets.token_urlsafe(32)`
when absent, and mirrors it in Redis as `session:{id}` with a sliding TTL
refreshed on every access. This identifies an anonymous Shopper so a Cart
has somewhere to live — it authenticates no one, per ADR-002.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.redis_client import get_redis_client
from app.settings import settings

logger = logging.getLogger("app.session")

SESSION_COOKIE_NAME = "session_id"
_SESSION_KEY_PREFIX = "session:"

# secrets.token_urlsafe(32) always produces 43 base64url characters (32 bytes
# -> ceil(32 * 8 / 6) = 43, with no '=' padding). A cookie value outside that
# exact shape is not a token we could have minted, so it is treated as
# absent rather than trusted and echoed back to Redis.
_TOKEN_LENGTH = 43
_TOKEN_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


@dataclass(frozen=True)
class SessionId:
    """An opaque anonymous session identifier.

    This is a bearer secret, not a display id: whoever holds `value` can
    act as the Shopper it belongs to (ADR-001), so it must never be logged
    or exposed anywhere but the `HttpOnly` cookie it travels in.
    """

    value: str

    @property
    def redis_key(self) -> str:
        """The Redis key for this session's record."""
        return f"{_SESSION_KEY_PREFIX}{self.value}"


def _mint_session_id() -> SessionId:
    """Generates a new opaque session token.

    Deliberately `secrets.token_urlsafe(32)` rather than a UUID: a UUID is
    built for uniqueness and is often derived from predictable inputs
    (timestamps, MAC addresses); this value instead has to resist
    *guessing*, because holding it is all that is required to act as the
    Shopper it names.
    """
    return SessionId(secrets.token_urlsafe(32))


def _is_well_formed(token: str) -> bool:
    """Returns whether `token` has the shape of a value this service mints."""
    return len(token) == _TOKEN_LENGTH and all(
        char in _TOKEN_ALPHABET for char in token
    )


class SessionStore:
    """Reads and writes the Redis-backed session record.

    The record itself carries no data beyond its own existence and TTL —
    `session:{id}` is a marker that a session is alive, refreshed on every
    access so an active Shopper never loses their Cart to an idle timeout.
    Later tasks (BE-07's Cart routes) extend this key's neighbourhood
    (`cart:{id}`) rather than this record's shape.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def touch(self, session_id: SessionId) -> None:
        """Creates or refreshes the session record with a sliding TTL.

        A Redis outage degrades this to a logged no-op rather than a failed
        request: cookie issuance does not depend on Redis being reachable,
        so browsing (and any route that isn't itself a Cart operation)
        keeps working. Whatever needs the record to actually exist — a
        Cart write in BE-07 — will surface the outage itself when it tries
        to read or write `cart:{id}` next to it.
        """
        try:
            await self._redis.set(session_id.redis_key, "1", ex=self._ttl_seconds)
        except RedisError:
            logger.error(
                "session store unreachable; cookie issued without a Redis record",
                extra={"redis_key": session_id.redis_key},
            )


def _read_session_cookie(request: Request) -> SessionId | None:
    """Returns the inbound session id, if the cookie is present and well-formed."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is not None and _is_well_formed(token):
        return SessionId(token)
    return None


def _set_session_cookie(response: Response, session_id: SessionId) -> None:
    """Sets the session cookie per ADR-001: HttpOnly, config-driven Secure, Lax.

    `secure` is read from `settings.cookie_secure` rather than hardcoded
    `True` — hardcoded, it drops the cookie silently over the plain HTTP the
    local Compose profile serves on.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id.value,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


async def get_session(request: Request, response: Response) -> SessionId:
    """FastAPI dependency identifying the anonymous Shopper making the request.

    Reuses the `session_id` cookie when present and well-formed; otherwise
    mints a new opaque token and sets it as the response cookie. Every call
    refreshes the sliding TTL on the Redis-backed session record. Route
    handlers should depend on this rather than reading the cookie
    themselves, so session plumbing lives in exactly one place.
    """
    session_id = _read_session_cookie(request)
    if session_id is None:
        session_id = _mint_session_id()
        _set_session_cookie(response, session_id)

    store = SessionStore(get_redis_client(), settings.session_ttl_seconds)
    await store.touch(session_id)

    return session_id
