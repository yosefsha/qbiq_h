"""Shared Redis clients.

Two process-wide singletons, both built from `REDIS_URL` and both backed by
`redis-py`'s own internal connection pool, so the pool and its configuration
stay in exactly one place per flavour:

- `get_redis_client` — `redis.asyncio.Redis`, used by `app.session` (an
  `async def` dependency).
- `get_sync_redis_client` — plain `redis.Redis`, used by
  `app.repositories.redis_cart_repository.RedisCartRepository`.

Why two clients rather than one: `CartRepository` in
`app.domain.repositories` is a **synchronous** Protocol (so that
`InMemoryRepository` can satisfy it without becoming `async`, per BE-02),
and `redis-py`'s sync and async clients are different classes that cannot
be swapped for one another. `RedisCartRepository`'s route handlers are
therefore plain `def`, not `async def` — see the comment on those routes in
`app.api.cart` for why that is safe under FastAPI.
"""

from __future__ import annotations

import redis
from redis.asyncio import Redis

from app.settings import settings

# A blackholed connection (host unreachable but not immediately refused, e.g.
# a security-group drop) hangs forever without an explicit timeout, pinning
# whichever threadpool worker made the call. A few seconds is generous for a
# same-VPC ElastiCache round trip and short enough that an outage surfaces as
# a fast error instead of a stuck request.
_SYNC_SOCKET_TIMEOUT_SECONDS = 3
_SYNC_SOCKET_CONNECT_TIMEOUT_SECONDS = 3

_client: Redis | None = None
_sync_client: redis.Redis | None = None


def get_redis_client() -> Redis:
    """Returns the process-wide async Redis client, creating it on first use.

    `decode_responses=True` so callers get `str` back rather than `bytes` —
    every value we store today is text (session markers, and JSON Cart
    payloads).
    """
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis_client() -> None:
    """Closes the process-wide async client and clears it, for test teardown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_sync_redis_client() -> redis.Redis:
    """Returns the process-wide sync Redis client, creating it on first use.

    Same `REDIS_URL` and `decode_responses=True` as the async client, plus
    explicit socket timeouts (see module docstring) that the async client
    does not need here, since nothing on that path currently runs from a
    context where a hang is this costly.
    """
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=_SYNC_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SYNC_SOCKET_CONNECT_TIMEOUT_SECONDS,
        )
    return _sync_client


def close_sync_redis_client() -> None:
    """Closes the process-wide sync client and clears it, for test teardown."""
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None
