"""Redis-backed caching decorator over a `ProductRepository` (BE-08).

Satisfies `ProductRepository` structurally and delegates every read to an
inner one, so caching is invisible to the HTTP layer and is removed by
pointing `app.api.deps.get_sql_product_repository` back at the inner
repository.

Keys
    ``products:q:{stable_hash(ProductQuery)}`` for listings, and
    ``products:id:{product_id}`` for single products. The id key is shared
    by `get_product` and `get_product_detail` — a `ProductDetail` is a
    strict superset of `Product` — so the payload carries a ``kind``
    discriminator. A detail entry satisfies both methods (projected down
    for the summary); a summary entry satisfies only `get_product`, and a
    detail read treats it as a miss and overwrites it with the richer
    payload. Without the discriminator a summary hit would silently answer
    a detail read with no `long_description` and no reviews.

Invalidation
    None. Nothing writes to the catalogue through this application — it
    changes only via `python -m app.seed` or a direct database edit — so
    entries expire by TTL alone. The consequence is real and accepted: a
    reseed is invisible to the API for up to `CACHE_TTL_SECONDS`.

Absent results are not cached. Distinguishing "cached absent" from "cache
miss" needs a sentinel, and buys nothing: a lookup by unknown id is already
a single indexed `SELECT` returning no rows.

`RedisError` is caught around every cache read and write, so an outage
degrades to a miss or a skipped write rather than a 500. The client must
carry socket timeouts (see `app.redis_client.get_sync_redis_client`), or an
unreachable-but-not-refused host hangs the calling thread instead of raising.
`UnknownSortKeyError` is deliberately raised outside any `try`, so it
propagates and is never cached — an invalid sort key must fail every time,
not just once.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, fields
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.domain.catalog import (
    Category,
    Product,
    ProductDetail,
    ProductPage,
    ProductQuery,
    Review,
    SortDirection,
    SortKey,
)
from app.domain.repositories import ProductRepository

logger = logging.getLogger(__name__)

_LIST_KEY_PREFIX = "products:q:"
_PRODUCT_KEY_PREFIX = "products:id:"

_KIND_PRODUCT = "product"
_KIND_PRODUCT_DETAIL = "product_detail"

#: Field names read back off a cached payload. Derived from the dataclasses
#: rather than restated, so adding a field to either type cannot leave this
#: module quietly dropping it on the way out of the cache.
_PRODUCT_FIELDS = tuple(f.name for f in fields(Product))
_PRODUCT_DETAIL_FIELDS = tuple(f.name for f in fields(ProductDetail))


def _enum_value(value: object) -> object:
    """Unwraps a `SortKey`/`SortDirection` to its `.value`, passing others through.

    `sort` and `direction` are *typed* as enums, but nothing at runtime stops
    a caller passing a raw string — the inner repositories defend against
    exactly that. A plain `str` has no `.value`, so it is used as-is, which
    keeps key derivation from raising ahead of the inner repository's own
    `UnknownSortKeyError`.
    """
    return value.value if isinstance(value, (SortKey, SortDirection)) else value


def _stable_hash(query: ProductQuery) -> str:
    """Hashes `query`'s field *values* in a fixed order.

    Not `hash(query)` (a frozen dataclass's hash depends on field declaration
    order, which is not a contract worth depending on) and not `repr(query)`
    (formatting is an implementation detail). Enums serialize by `.value`, so
    `SortKey.NAME` and `"name"` cannot hash differently, and the key stays
    stable across process restarts. Two queries with identical values but
    different keyword ordering therefore share a key.
    """
    values: tuple[Any, ...] = (
        query.name_contains,
        query.category_slug,
        _enum_value(query.sort),
        _enum_value(query.direction),
        query.limit,
        query.offset,
    )
    payload = json.dumps(values, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _list_key(query: ProductQuery) -> str:
    return f"{_LIST_KEY_PREFIX}{_stable_hash(query)}"


def _product_key(product_id: str) -> str:
    return f"{_PRODUCT_KEY_PREFIX}{product_id}"


def _encode(product: Product) -> str:
    """Serializes a `Product`, tagging it by what it actually is.

    `asdict` walks nested dataclasses, so `category` and `reviews` come along
    for free. The kind is taken from the runtime type rather than the calling
    method: `get_product` is free to return a `ProductDetail` (Liskov), and
    when it does, storing it as a detail is strictly better than truncating.
    """
    payload = asdict(product)
    payload["kind"] = (
        _KIND_PRODUCT_DETAIL if isinstance(product, ProductDetail) else _KIND_PRODUCT
    )
    return json.dumps(payload)


def _to_product(data: dict[str, Any]) -> Product:
    """Rebuilds the summary shape, ignoring any detail-only fields present."""
    known = {name: data[name] for name in _PRODUCT_FIELDS}
    known["category"] = Category(**data["category"])
    return Product(**known)


def _to_product_detail(data: dict[str, Any]) -> ProductDetail:
    known = {name: data[name] for name in _PRODUCT_DETAIL_FIELDS}
    known["category"] = Category(**data["category"])
    known["reviews"] = tuple(Review(**review) for review in data["reviews"])
    return ProductDetail(**known)


def _decode_product(data: dict[str, Any]) -> Product | None:
    """A hit of either kind answers a summary read."""
    if data.get("kind") not in (_KIND_PRODUCT, _KIND_PRODUCT_DETAIL):
        return None
    return _to_product(data)


def _decode_product_detail(data: dict[str, Any]) -> ProductDetail | None:
    """Only a detail hit answers a detail read; a summary hit is a miss."""
    if data.get("kind") != _KIND_PRODUCT_DETAIL:
        return None
    return _to_product_detail(data)


def _encode_page(page: ProductPage) -> str:
    return json.dumps(
        {"items": [asdict(item) for item in page.items], "total": page.total}
    )


def _decode_page(data: dict[str, Any]) -> ProductPage:
    return ProductPage(
        items=tuple(_to_product(item) for item in data["items"]), total=data["total"]
    )


class CachedProductRepository:
    """`ProductRepository` decorator caching reads in Redis under a TTL.

    Holds no engine, session, or pool of its own: anything not usable from
    the cache is asked of `inner`. See the module docstring for key layout,
    invalidation, and failure handling.
    """

    def __init__(
        self, inner: ProductRepository, redis: Redis, ttl_seconds: int
    ) -> None:
        self._inner = inner
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    # -- ProductRepository ---------------------------------------------

    def list_products(self, query: ProductQuery) -> ProductPage:
        key = _list_key(query)
        cached = self._read(key, _decode_page)
        if cached is not None:
            return cached

        # Outside any try/except: UnknownSortKeyError must propagate uncached.
        page = self._inner.list_products(query)
        self._write(key, _encode_page(page))
        return page

    def get_product(self, product_id: str) -> Product | None:
        key = _product_key(product_id)
        cached = self._read(key, _decode_product)
        if cached is not None:
            return cached

        product = self._inner.get_product(product_id)
        if product is not None:
            self._write(key, _encode(product))
        return product

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        key = _product_key(product_id)
        cached = self._read(key, _decode_product_detail)
        if cached is not None:
            return cached

        detail = self._inner.get_product_detail(product_id)
        if detail is not None:
            self._write(key, _encode(detail))
        return detail

    def list_categories(self) -> tuple[Category, ...]:
        """Delegates uncached: a handful of rows, one unbounded query."""
        return self._inner.list_categories()

    # -- Redis, where any failure is a miss ------------------------------

    def _read[T](
        self, key: str, decode: Callable[[dict[str, Any]], T | None]
    ) -> T | None:
        """Returns a decoded cache hit, or `None` for a miss of any cause.

        A miss, an outage, and a malformed or wrong-kind entry are all the
        same outcome to the caller — ask the inner repository — so they
        collapse here rather than at three call sites.
        """
        try:
            raw = self._redis.get(key)
        except RedisError:
            logger.warning(
                "Redis unavailable reading cache key=%s; falling back to source",
                key,
                exc_info=True,
            )
            return None

        if raw is None:
            return None
        try:
            return decode(json.loads(raw))
        except (KeyError, TypeError, ValueError):
            logger.warning("Discarding malformed cache entry for key=%s", key)
            return None

    def _write(self, key: str, value: str) -> None:
        try:
            self._redis.set(key, value, ex=self._ttl_seconds)
        except RedisError:
            logger.warning(
                "Redis unavailable writing cache key=%s; skipping cache write",
                key,
                exc_info=True,
            )
