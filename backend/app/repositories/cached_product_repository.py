"""Redis-backed caching decorator over a `ProductRepository` (BE-08).

`CachedProductRepository` satisfies `app.domain.repositories.ProductRepository`
structurally and delegates every read to an inner `ProductRepository` (in
practice `app.repositories.sql_product_repository.SqlProductRepository`), so
caching is invisible to the HTTP layer: `app/api/products.py` never knows it
is talking to a cache, and the cache can be removed by changing the single
line of dependency wiring in `app.api.deps.get_sql_product_repository` back
to yielding the inner repository directly.

Key layout
----------
- Listings: ``products:q:{stable_hash(ProductQuery)}`` — the hash is derived
  from an explicit, fixed-order tuple of `ProductQuery`'s field *values*
  (never `hash(query)` or `repr(query)`), so two queries built with keyword
  arguments in a different order, but identical values, land on the same
  key. `SortKey`/`SortDirection` are serialized via `.value`, not object
  identity, so the hash is stable across process restarts too.
- Products, by id: ``products:id:{product_id}``. This single key is shared
  between `get_product` (the summary shape) and `get_product_detail` (the
  summary plus `long_description` and `reviews`), because a `ProductDetail`
  is a strict superset of `Product`'s fields. The stored JSON carries a
  `"kind"` discriminator (`"product"` or `"product_detail"`) so a read knows
  what it has:
    * `get_product` accepts a hit of either kind, projecting just the
      `Product` fields out of a cached `ProductDetail` when that's what's
      there.
    * `get_product_detail` only accepts a hit of kind `"product_detail"`; a
      `"product"` hit lacks `long_description`/`reviews`, so it is treated
      as a cache miss, the inner repository is asked for the full detail,
      and the richer payload overwrites the entry. A detail entry is never
      downgraded by a later `get_product` call: that path only writes when
      its own cache read was a miss, so an existing `"product_detail"` hit
      is returned (projected to the summary fields) rather than replaced —
      see `CachedProductRepository.get_product`.

Invalidation strategy
----------------------
There is no write path through this application: the catalogue changes only
via `python -m app.seed` or a direct database edit, never through an HTTP
request. Consequently, **this class performs no active invalidation at
all** — every entry simply expires after `settings.cache_ttl_seconds`
(`CACHE_TTL_SECONDS`) and is refetched from the inner repository on the next
request past that point. The direct consequence: a catalogue change (a
reseed, a manually edited row) is invisible to the API for up to
`CACHE_TTL_SECONDS` after it happens, worst case. That staleness window is
an accepted trade-off for a read-only catalogue, not an oversight — nothing
in this module reacts to a seed run, and nothing needs to.

Cache-miss vs. cached-absent
-----------------------------
`get_product` and `get_product_detail` do **not** cache a `None` result.
Reasoning: distinguishing "cached absent" from "cache miss" would need a
sentinel value alongside real payloads, and gains little here — a lookup by
a nonexistent id is already a single indexed `SELECT` returning zero rows in
`SqlProductRepository`, i.e. cheap, so there is no expensive read to shield
by caching the negative result. Only successful reads are cached.

Failure handling
-----------------
`redis.exceptions.RedisError` is caught around every cache read and write.
An outage degrades to a cache miss (reads always fall through to the inner
repository) or a skipped write (writes are best-effort) — never a 500. The
`redis.Redis` client this class is constructed with must carry socket
timeouts (see `app.redis_client.get_sync_redis_client`), or an unreachable-
but-not-refused host would hang the calling thread indefinitely instead of
raising `RedisError` promptly.

`UnknownSortKeyError` is never caught here: `list_products` calls the inner
repository directly (no `try`/`except` around that call), so the error
propagates to the caller unchanged and, critically, is never cached — an
invalid sort key must fail on every call, not just the first.
"""

from __future__ import annotations

import hashlib
import json
import logging
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


def _stable_hash(query: ProductQuery) -> str:
    """Derives a deterministic cache key suffix from `query`'s field values.

    An explicit, fixed-order tuple of values — not `hash(query)` (a frozen
    dataclass's hash is a function of field values *and* their declaration
    order, undocumented and not a contract we want to depend on) and not
    `repr(query)` (whose formatting is an implementation detail). Enum
    members are serialized via `.value` so `SortKey.NAME` and the literal
    string `"name"` never hash differently. Two `ProductQuery` instances
    built with keyword arguments in different order but identical values
    always produce the same tuple here, and therefore the same key.

    `sort`/`direction` are typed as `SortKey`/`SortDirection`, but nothing
    at runtime stops a caller constructing a `ProductQuery` with a raw
    string instead (the inner repositories defend against exactly this —
    see `SqlProductRepository.list_products`'s `_SORT_COLUMNS` lookup). A
    plain `str` has no `.value`, so it is used as-is rather than attribute-
    accessed, keeping key derivation itself from raising ahead of the
    inner repository's own `UnknownSortKeyError`.
    """
    sort_value = query.sort.value if isinstance(query.sort, SortKey) else query.sort
    direction_value = (
        query.direction.value
        if isinstance(query.direction, SortDirection)
        else query.direction
    )
    fields: tuple[Any, ...] = (
        query.name_contains,
        query.category_slug,
        sort_value,
        direction_value,
        query.limit,
        query.offset,
    )
    payload = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _list_key(query: ProductQuery) -> str:
    return f"{_LIST_KEY_PREFIX}{_stable_hash(query)}"


def _product_key(product_id: str) -> str:
    return f"{_PRODUCT_KEY_PREFIX}{product_id}"


def _category_to_dict(category: Category) -> dict[str, Any]:
    return {"slug": category.slug, "name": category.name}


def _category_from_dict(data: dict[str, Any]) -> Category:
    return Category(slug=data["slug"], name=data["name"])


def _review_to_dict(review: Review) -> dict[str, Any]:
    return {
        "id": review.id,
        "author": review.author,
        "rating": review.rating,
        "body": review.body,
    }


def _review_from_dict(data: dict[str, Any]) -> Review:
    return Review(
        id=data["id"], author=data["author"], rating=data["rating"], body=data["body"]
    )


def _product_fields(product: Product) -> dict[str, Any]:
    """The fields shared by `Product` and `ProductDetail`, as a dict."""
    return {
        "id": product.id,
        "name": product.name,
        "price_minor": product.price_minor,
        "currency": product.currency,
        "short_description": product.short_description,
        "thumbnail_url": product.thumbnail_url,
        "category": _category_to_dict(product.category),
    }


def _product_from_fields(data: dict[str, Any]) -> Product:
    return Product(
        id=data["id"],
        name=data["name"],
        price_minor=data["price_minor"],
        currency=data["currency"],
        short_description=data["short_description"],
        thumbnail_url=data["thumbnail_url"],
        category=_category_from_dict(data["category"]),
    )


def _product_detail_from_fields(data: dict[str, Any]) -> ProductDetail:
    return ProductDetail(
        id=data["id"],
        name=data["name"],
        price_minor=data["price_minor"],
        currency=data["currency"],
        short_description=data["short_description"],
        thumbnail_url=data["thumbnail_url"],
        category=_category_from_dict(data["category"]),
        long_description=data["long_description"],
        reviews=tuple(_review_from_dict(review) for review in data["reviews"]),
    )


def _encode_product(product: Product) -> str:
    payload = {"kind": _KIND_PRODUCT, **_product_fields(product)}
    return json.dumps(payload)


def _encode_product_detail(detail: ProductDetail) -> str:
    payload = {
        "kind": _KIND_PRODUCT_DETAIL,
        **_product_fields(detail),
        "long_description": detail.long_description,
        "reviews": [_review_to_dict(review) for review in detail.reviews],
    }
    return json.dumps(payload)


def _encode_page(page: ProductPage) -> str:
    payload = {
        "items": [_product_fields(item) for item in page.items],
        "total": page.total,
    }
    return json.dumps(payload)


def _decode_page(raw: str) -> ProductPage:
    data = json.loads(raw)
    items = tuple(_product_from_fields(item) for item in data["items"])
    return ProductPage(items=items, total=data["total"])


class CachedProductRepository:
    """`ProductRepository` decorator that caches reads in Redis with a TTL.

    Holds no engine, session, or connection pool of its own: `inner` is
    asked for anything not found (or not usable) in the cache, and `redis`
    is a plain, synchronous `redis.Redis` — see the module docstring for the
    key layout, invalidation strategy, and failure handling this class
    implements.
    """

    def __init__(
        self, inner: ProductRepository, redis: Redis, ttl_seconds: int
    ) -> None:
        self._inner = inner
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    # -- ProductRepository ---------------------------------------------

    def list_products(self, query: ProductQuery) -> ProductPage:
        """Returns a cached page for `query`, or fetches and caches one.

        `UnknownSortKeyError` is raised by `self._inner.list_products`
        outside of any `try`/`except` here, so it propagates unchanged and
        is never written to the cache.
        """
        key = _list_key(query)
        raw = self._safe_get(key)
        if raw is not None:
            try:
                return _decode_page(raw)
            except (KeyError, TypeError, ValueError):
                logger.warning("Discarding malformed cache entry for key=%s", key)

        page = self._inner.list_products(query)
        self._safe_set(key, _encode_page(page))
        return page

    def get_product(self, product_id: str) -> Product | None:
        """Returns the summary `Product` for `product_id`, cached or not.

        Accepts a cached entry of either kind: a `"product_detail"` hit
        already carries every `Product` field, so it is projected down
        rather than treated as a miss. A miss reaches the inner repository
        and, on success, is cached as kind `"product"` — see the module
        docstring for why this never downgrades an existing detail entry.
        """
        key = _product_key(product_id)
        cached = self._decode_cached_product(key)
        if cached is not None:
            return cached

        product = self._inner.get_product(product_id)
        if product is not None:
            self._safe_set(key, _encode_product(product))
        return product

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        """Returns the full `ProductDetail` for `product_id`, cached or not.

        Only a `"product_detail"`-kind cache hit satisfies this method; a
        `"product"`-kind hit (written by `get_product`) lacks
        `long_description`/`reviews`, so it is treated as a miss here, the
        inner repository is asked for the full detail, and the resulting
        payload overwrites whatever summary-only entry was cached.
        """
        key = _product_key(product_id)
        cached = self._decode_cached_product_detail(key)
        if cached is not None:
            return cached

        detail = self._inner.get_product_detail(product_id)
        if detail is not None:
            self._safe_set(key, _encode_product_detail(detail))
        return detail

    def list_categories(self) -> tuple[Category, ...]:
        """Delegates directly, uncached.

        Out of scope per the issue: caching is scoped to product listings
        and product reads. The category table is small, already unbounded
        in `SqlProductRepository.list_categories`, and edited only via the
        same out-of-band path as the rest of the catalogue.
        """
        return self._inner.list_categories()

    # -- cache reads ------------------------------------------------------

    def _decode_cached_product(self, key: str) -> Product | None:
        raw = self._safe_get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if data.get("kind") not in (_KIND_PRODUCT, _KIND_PRODUCT_DETAIL):
                return None
            return _product_from_fields(data)
        except (KeyError, TypeError, ValueError):
            logger.warning("Discarding malformed cache entry for key=%s", key)
            return None

    def _decode_cached_product_detail(self, key: str) -> ProductDetail | None:
        raw = self._safe_get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if data.get("kind") != _KIND_PRODUCT_DETAIL:
                return None
            return _product_detail_from_fields(data)
        except (KeyError, TypeError, ValueError):
            logger.warning("Discarding malformed cache entry for key=%s", key)
            return None

    # -- Redis, with outage degrading to a miss --------------------------

    def _safe_get(self, key: str) -> str | None:
        try:
            return self._redis.get(key)
        except RedisError:
            logger.warning(
                "Redis unavailable reading cache key=%s; falling back to source",
                key,
                exc_info=True,
            )
            return None

    def _safe_set(self, key: str, value: str) -> None:
        try:
            self._redis.set(key, value, ex=self._ttl_seconds)
        except RedisError:
            logger.warning(
                "Redis unavailable writing cache key=%s; skipping cache write",
                key,
                exc_info=True,
            )
