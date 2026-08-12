"""Tests for `CachedProductRepository` (BE-08).

Two kinds of test live here:

- Pure tests of `_stable_hash` / `_list_key` — no Redis involved — covering
  key stability under keyword-argument reordering and key divergence per
  filter field. These never skip.
- Integration-style tests against a **real Redis**, following the pattern in
  `tests/test_session.py`: reached via `TEST_REDIS_PORT` (default `6379`),
  skipping gracefully if unreachable. To avoid colliding with other agents
  sharing the same Redis instance at `localhost:56379`, these use a
  dedicated logical database (`/15`, distinct from the `/0` sessions and
  Cart tests use) and always clean up the exact keys they touch rather than
  flushing the database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
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
from app.domain.errors import UnknownSortKeyError
from app.domain.repositories import ProductRepository
from app.repositories.cached_product_repository import (
    CachedProductRepository,
    _list_key,
    _product_key,
    _stable_hash,
)

_TEST_REDIS_URL = os.environ.get(
    "TEST_REDIS_URL_CACHE_DB",
    f"redis://localhost:{os.environ.get('TEST_REDIS_PORT', '6379')}/15",
)

_TTL_SECONDS = 60


class _CountingProductRepository:
    """A spy `ProductRepository`: counts calls and returns fixed data.

    Satisfies the Protocol structurally; used as the inner repository so
    tests can assert "exactly one round trip" by counting rather than by
    timing, per the issue's explicit instruction.
    """

    def __init__(
        self,
        page: ProductPage | None = None,
        product: Product | None = None,
        detail: ProductDetail | None = None,
    ) -> None:
        self.list_calls: list[ProductQuery] = []
        self.get_calls: list[str] = []
        self.get_detail_calls: list[str] = []
        self._page = page if page is not None else ProductPage(items=(), total=0)
        self._product = product
        self._detail = detail

    def list_products(self, query: ProductQuery) -> ProductPage:
        self.list_calls.append(query)
        return self._page

    def list_categories(self) -> tuple[Category, ...]:
        return ()

    def get_product(self, product_id: str) -> Product | None:
        self.get_calls.append(product_id)
        return self._product

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        self.get_detail_calls.append(product_id)
        return self._detail


class _SortKeyRaisingRepository:
    """A minimal inner repository whose `list_products` always raises
    `UnknownSortKeyError`, for asserting the error propagates uncached."""

    def __init__(self) -> None:
        self.list_calls = 0

    def list_products(self, query: ProductQuery) -> ProductPage:
        self.list_calls += 1
        raise UnknownSortKeyError(query.sort)

    def list_categories(self) -> tuple[Category, ...]:
        return ()

    def get_product(self, product_id: str) -> Product | None:
        return None

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        return None


def _category(slug: str = "e-books") -> Category:
    return Category(slug=slug, name="E-Books")


def _product(product_id: str = "1", name: str = "Sample Product") -> Product:
    return Product(
        id=product_id,
        name=name,
        price_minor=1999,
        currency="USD",
        short_description="A sample product.",
        thumbnail_url="https://example.com/thumb.png",
        category=_category(),
    )


def _detail(product_id: str = "1") -> ProductDetail:
    base = _product(product_id)
    return ProductDetail(
        id=base.id,
        name=base.name,
        price_minor=base.price_minor,
        currency=base.currency,
        short_description=base.short_description,
        thumbnail_url=base.thumbnail_url,
        category=base.category,
        long_description="A much longer description of the sample product.",
        reviews=(
            Review(id="1", author="Ana", rating=5, body="Loved it."),
            Review(id="2", author="Ben", rating=3, body="It was fine."),
        ),
    )


@pytest.fixture(name="redis_client")
def redis_client_fixture() -> Iterator[Redis]:
    """A real Redis client on a dedicated logical database, skipping if
    unreachable rather than erroring — see the module docstring."""
    client = Redis.from_url(
        _TEST_REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
    except RedisError as exc:
        pytest.skip(f"Redis is not reachable at {_TEST_REDIS_URL}: {exc}")

    yield client

    client.close()


def _unreachable_redis_client() -> Redis:
    """A client pointed at a port nothing listens on, with short timeouts,
    matching the pattern in `tests/test_session.py` for simulating an
    outage without a real one."""
    return Redis.from_url(
        "redis://127.0.0.1:1/0",
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


# -- key derivation: pure, no Redis -----------------------------------------


def test_queries_differing_only_in_keyword_order_share_a_cache_key() -> None:
    built_one_order = ProductQuery(
        name_contains="python",
        category_slug="e-books",
        sort=SortKey.PRICE,
        direction=SortDirection.DESC,
        limit=10,
        offset=5,
    )
    built_other_order = ProductQuery(
        offset=5,
        limit=10,
        direction=SortDirection.DESC,
        sort=SortKey.PRICE,
        category_slug="e-books",
        name_contains="python",
    )

    assert _stable_hash(built_one_order) == _stable_hash(built_other_order)
    assert _list_key(built_one_order) == _list_key(built_other_order)


def test_queries_differing_in_any_filter_value_produce_different_keys() -> None:
    base = ProductQuery(
        name_contains="python",
        category_slug="e-books",
        sort=SortKey.NAME,
        direction=SortDirection.ASC,
        limit=10,
        offset=0,
    )
    variants = {
        "name_contains": ProductQuery(
            name_contains="rust",
            category_slug="e-books",
            sort=SortKey.NAME,
            direction=SortDirection.ASC,
            limit=10,
            offset=0,
        ),
        "category_slug": ProductQuery(
            name_contains="python",
            category_slug="courses",
            sort=SortKey.NAME,
            direction=SortDirection.ASC,
            limit=10,
            offset=0,
        ),
        "sort": ProductQuery(
            name_contains="python",
            category_slug="e-books",
            sort=SortKey.PRICE,
            direction=SortDirection.ASC,
            limit=10,
            offset=0,
        ),
        "direction": ProductQuery(
            name_contains="python",
            category_slug="e-books",
            sort=SortKey.NAME,
            direction=SortDirection.DESC,
            limit=10,
            offset=0,
        ),
        "limit": ProductQuery(
            name_contains="python",
            category_slug="e-books",
            sort=SortKey.NAME,
            direction=SortDirection.ASC,
            limit=20,
            offset=0,
        ),
        "offset": ProductQuery(
            name_contains="python",
            category_slug="e-books",
            sort=SortKey.NAME,
            direction=SortDirection.ASC,
            limit=10,
            offset=5,
        ),
    }

    base_key = _list_key(base)
    for field, variant in variants.items():
        assert _list_key(variant) != base_key, f"{field} did not change the key"

    # And every variant is distinct from every other variant too.
    all_keys = {base_key, *(_list_key(v) for v in variants.values())}
    assert len(all_keys) == 1 + len(variants)


# -- Protocol conformance -----------------------------------------------


def test_cached_product_repository_satisfies_product_repository() -> None:
    repository = CachedProductRepository(
        _CountingProductRepository(), _unreachable_redis_client(), _TTL_SECONDS
    )

    assert isinstance(repository, ProductRepository)


# -- repeated identical query: exactly one SQL round trip -------------------


def test_repeated_identical_list_query_hits_inner_repository_once(
    redis_client: Redis,
) -> None:
    page = ProductPage(items=(_product("1"), _product("2")), total=2)
    inner = _CountingProductRepository(page=page)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    query = ProductQuery(category_slug="round-trip-once", limit=10, offset=0)
    key = _list_key(query)

    try:
        first = repository.list_products(query)
        second = repository.list_products(query)

        assert len(inner.list_calls) == 1
        assert first == page
        assert second == page
    finally:
        redis_client.delete(key)


def test_repeated_identical_get_product_hits_inner_repository_once(
    redis_client: Redis,
) -> None:
    product = _product("round-trip-product-1")
    inner = _CountingProductRepository(product=product)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    key = _product_key(product.id)

    try:
        first = repository.get_product(product.id)
        second = repository.get_product(product.id)

        assert len(inner.get_calls) == 1
        assert first == product
        assert second == product
    finally:
        redis_client.delete(key)


# -- Redis outage degrades to a cache miss, not a 500 ------------------------


def test_redis_outage_degrades_to_cache_miss_on_list_products() -> None:
    page = ProductPage(items=(_product("1"),), total=1)
    inner = _CountingProductRepository(page=page)
    repository = CachedProductRepository(
        inner, _unreachable_redis_client(), _TTL_SECONDS
    )
    query = ProductQuery(category_slug="outage")

    result = repository.list_products(query)

    assert result == page
    assert len(inner.list_calls) == 1


def test_redis_outage_degrades_to_cache_miss_on_get_product() -> None:
    product = _product("outage-product")
    inner = _CountingProductRepository(product=product)
    repository = CachedProductRepository(
        inner, _unreachable_redis_client(), _TTL_SECONDS
    )

    result = repository.get_product(product.id)

    assert result == product
    assert len(inner.get_calls) == 1


def test_redis_outage_degrades_to_cache_miss_on_get_product_detail() -> None:
    detail = _detail("outage-detail")
    inner = _CountingProductRepository(detail=detail)
    repository = CachedProductRepository(
        inner, _unreachable_redis_client(), _TTL_SECONDS
    )

    result = repository.get_product_detail(detail.id)

    assert result == detail
    assert len(inner.get_detail_calls) == 1


# -- ProductDetail round-trips faithfully ------------------------------------


def test_cached_product_detail_round_trips_with_reviews_and_long_description(
    redis_client: Redis,
) -> None:
    detail = _detail("detail-round-trip-1")
    inner = _CountingProductRepository(detail=detail)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    key = _product_key(detail.id)

    try:
        first = repository.get_product_detail(detail.id)
        second = repository.get_product_detail(detail.id)

        assert len(inner.get_detail_calls) == 1
        assert isinstance(second, ProductDetail)
        assert second == detail
        assert second.long_description == detail.long_description
        assert second.reviews == detail.reviews
        assert first == second
    finally:
        redis_client.delete(key)


def test_get_product_detail_is_not_satisfied_by_a_cached_summary(
    redis_client: Redis,
) -> None:
    """A `get_product` cache write must not corrupt a later detail read."""
    product = _product("summary-then-detail-1")
    detail = _detail("summary-then-detail-1")
    inner = _CountingProductRepository(product=product, detail=detail)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    key = _product_key(product.id)

    try:
        summary = repository.get_product(product.id)
        assert summary == product
        assert len(inner.get_calls) == 1

        full = repository.get_product_detail(product.id)
        assert full == detail
        assert isinstance(full, ProductDetail)
        assert len(inner.get_detail_calls) == 1

        # The upgraded entry now satisfies a second detail read from cache.
        full_again = repository.get_product_detail(product.id)
        assert full_again == detail
        assert len(inner.get_detail_calls) == 1
    finally:
        redis_client.delete(key)


# -- TTL is actually set ------------------------------------------------


def test_ttl_is_set_on_cached_list_key(redis_client: Redis) -> None:
    page = ProductPage(items=(_product("1"),), total=1)
    inner = _CountingProductRepository(page=page)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    query = ProductQuery(category_slug="ttl-check-list")
    key = _list_key(query)

    try:
        repository.list_products(query)

        ttl = redis_client.ttl(key)
        assert 0 < ttl <= _TTL_SECONDS
    finally:
        redis_client.delete(key)


def test_ttl_is_set_on_cached_product_key(redis_client: Redis) -> None:
    product = _product("ttl-check-product-1")
    inner = _CountingProductRepository(product=product)
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    key = _product_key(product.id)

    try:
        repository.get_product(product.id)

        ttl = redis_client.ttl(key)
        assert 0 < ttl <= _TTL_SECONDS
    finally:
        redis_client.delete(key)


# -- UnknownSortKeyError propagates uncached ---------------------------------


def test_unknown_sort_key_error_propagates_and_is_not_cached(
    redis_client: Redis,
) -> None:
    inner = _SortKeyRaisingRepository()
    repository = CachedProductRepository(inner, redis_client, _TTL_SECONDS)
    # A raw string, not a `SortKey` member: nothing at runtime stops this,
    # and the inner repository must still be the one to reject it (see
    # `SqlProductRepository`'s and `InMemoryRepository`'s own tests of the
    # same defence).
    query = ProductQuery(
        category_slug="unknown-sort",
        sort="not-a-real-sort-key",  # type: ignore[arg-type]
    )
    key = _list_key(query)

    try:
        with pytest.raises(UnknownSortKeyError):
            repository.list_products(query)
        with pytest.raises(UnknownSortKeyError):
            repository.list_products(query)

        assert inner.list_calls == 2
        assert redis_client.get(key) is None
    finally:
        redis_client.delete(key)
