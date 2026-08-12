"""Shared Redis client.

A single process-wide `redis.asyncio.Redis` instance, built from
`REDIS_URL` on first use and backed by `redis-py`'s own internal connection
pool. Every module that needs Redis (sessions today; Carts and the
product-query cache in later tasks) imports `get_redis_client` rather than
constructing its own connection, so the connection pool and its
configuration stay in exactly one place.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.settings import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Returns the process-wide Redis client, creating it on first use.

    `decode_responses=True` so callers get `str` back rather than `bytes` —
    every value we store today is text (session markers, and later, JSON
    Cart payloads).
    """
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis_client() -> None:
    """Closes the process-wide client and clears it, for test teardown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
