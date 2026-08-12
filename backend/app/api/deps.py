"""FastAPI dependency providers that need a concrete storage implementation.

Kept out of `app/api/products.py` deliberately: that module must not import
SQLAlchemy (an explicit Done-when on BE-05), but building a request-scoped
`SqlProductRepository` needs a `sqlalchemy.orm.Session` from
`app.db.session.SessionLocal`. `app.main` overrides
`app.api.products.get_product_repository` with `get_sql_product_repository`
at startup; tests override the same key with an
`app.domain.fakes.InMemoryRepository` instead (see `test_products_api.py`),
so this module is never imported by the test suite at all.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.db.session import SessionLocal
from app.domain.repositories import ProductRepository
from app.redis_client import get_sync_redis_client
from app.repositories.cached_product_repository import CachedProductRepository
from app.repositories.sql_product_repository import SqlProductRepository
from app.settings import settings


def get_sql_product_repository() -> Iterator[ProductRepository]:
    """Yields a `SqlProductRepository` bound to a request-scoped `Session`,
    wrapped in `CachedProductRepository` (BE-08).

    The session is opened fresh for this request and always closed in
    `finally`, even if the route handler raises — never built once at module
    level, which would share one connection across every concurrent request.
    The Redis client, by contrast, is the process-wide singleton from
    `app.redis_client` (its own connection pool, safe to share). To remove
    the cache entirely, change the `yield` line back to
    `yield SqlProductRepository(session)`.
    """
    session = SessionLocal()
    try:
        yield CachedProductRepository(
            SqlProductRepository(session),
            get_sync_redis_client(),
            settings.cache_ttl_seconds,
        )
    finally:
        session.close()
