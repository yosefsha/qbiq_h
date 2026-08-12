"""Tests for the Cart API (BE-07): routes, and `RedisCartRepository`.

Two groups, per the issue's own split:

- Route tests drive `app.main.app` through `TestClient`, with
  `get_cart_repository` overridden to an `InMemoryRepository` (BE-02) — no
  real Redis needed, and the same fake stands in for both `CartRepository`
  and `ProductRepository` since it satisfies both Protocols.
- Repository tests exercise `RedisCartRepository` directly against a real
  Redis, skipping gracefully (mirroring `tests/test_seed.py`'s Postgres
  skip) when it is unreachable. They run against a distinct logical Redis
  database — `REDIS_URL`'s database index swapped for `_CART_TEST_DB_INDEX`
  — and always delete the keys they create, since this Redis instance is
  shared with other agents' test runs.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

import app.session as session_module
from app.api.cart import get_cart_repository
from app.domain.catalog import Category, Product
from app.domain.errors import UnknownProductError
from app.domain.fakes import InMemoryRepository
from app.domain.repositories import CartRepository
from app.main import app
from app.repositories.redis_cart_repository import (
    MAX_LINE_ITEM_QUANTITY,
    RedisCartRepository,
)
from app.settings import settings


@pytest.fixture(autouse=True)
def _fresh_session_redis_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gives `get_session` a brand-new async Redis client on every call.

    `TestClient(app)`, used as a context manager below because
    `async def get_session` needs a running event loop, opens a *fresh*
    event loop each time it is entered — and some tests below enter it
    more than once (isolation tests comparing two Shoppers). The
    process-wide `app.redis_client.get_redis_client()` caches one client
    at module scope, so reusing it across two different event loops binds
    it to whichever loop happened to be running when it was first used,
    and every call after that fails with "Event loop is closed" or
    "attached to a different loop". `get_session` already calls
    `get_redis_client()` fresh on every request rather than caching it
    itself, so returning a brand-new client from this patched function on
    every call (never reused across requests, let alone across loops)
    sidesteps the problem entirely for the tests below. Same technique
    `tests/test_session.py` uses, generalized from "fresh per test" to
    "fresh per call" because this file needs more than one loop per test.
    """
    monkeypatch.setattr(
        session_module,
        "get_redis_client",
        lambda: AsyncRedis.from_url(settings.redis_url, decode_responses=True),
    )


EBOOKS = Category(slug="ebooks", name="E-books")
COURSES = Category(slug="courses", name="Courses")


def _product(
    product_id: str,
    name: str,
    price_minor: int,
    *,
    category: Category = EBOOKS,
    currency: str = "USD",
) -> Product:
    return Product(
        id=product_id,
        name=name,
        price_minor=price_minor,
        currency=currency,
        short_description=f"{name} short description",
        thumbnail_url=f"https://example.com/{product_id}.png",
        category=category,
    )


PYTHON_BOOK = _product("p-python", "Python Fundamentals", 1999)
RUST_BOOK = _product("p-rust", "Rust in Practice", 2999)
ALGEBRA_COURSE = _product("p-algebra", "Algebra Refresher", 999, category=COURSES)


def _catalogue(
    products: Iterable[Product] = (PYTHON_BOOK, RUST_BOOK, ALGEBRA_COURSE),
) -> InMemoryRepository:
    return InMemoryRepository(products=products)


# `InMemoryRepository` (BE-02) exposes no method to change or remove a
# product after construction — its catalogue is fixed at seed time, by
# design. The price-change and product-deletion tests below reach into its
# `_products` dict directly to simulate the catalogue changing between two
# requests, which is exactly the scenario `RedisCartRepository` has to
# tolerate (re-reading a price, or finding the product gone, on every call).


class _ClientWithRepository:
    """A `TestClient` wired to a dependency-overridden `CartRepository`.

    Entered as a context manager (see `app.main.app`'s own `TestClient`
    usage in `tests/test_session.py`): this keeps one event loop alive for
    the whole `with` block, which the `async def get_session` dependency
    every Cart route depends on needs across more than one request. Works
    with any `CartRepository` — an `InMemoryRepository` for the fake-backed
    route tests, or a real `RedisCartRepository` for the handful that need
    to exercise this task's actual Redis-backed behaviour through the HTTP
    layer rather than the Protocol's minimal guarantees.
    """

    def __init__(self, repository: CartRepository) -> None:
        self.repository = repository
        self._test_client: TestClient | None = None

    def __enter__(self) -> TestClient:
        app.dependency_overrides[get_cart_repository] = lambda: self.repository
        self._test_client = TestClient(app).__enter__()
        return self._test_client

    def __exit__(self, *exc_info: object) -> None:
        assert self._test_client is not None
        self._test_client.__exit__(*exc_info)
        app.dependency_overrides.pop(get_cart_repository, None)


def _client(
    products: Iterable[Product] = (PYTHON_BOOK, RUST_BOOK, ALGEBRA_COURSE),
) -> _ClientWithRepository:
    return _ClientWithRepository(_catalogue(products))


# -- Route tests: GET /api/cart -------------------------------------------


def test_get_cart_for_new_session_is_empty_with_default_currency() -> None:
    with _client() as client:
        response = client.get("/api/cart")

    assert response.status_code == 200
    assert response.json() == {"items": [], "totalMinor": 0, "currency": "USD"}
    assert response.cookies.get("session_id")


def test_get_cart_never_reads_a_session_id_from_query_or_header() -> None:
    """ADR-001: only the cookie identifies a Shopper, never a client-supplied id."""
    with _client([PYTHON_BOOK]) as client:
        seeded = client.post(
            "/api/cart/items", json={"productId": "p-python", "quantity": 1}
        )
        session_cookie = seeded.cookies["session_id"]

        # Same client, but with its cookie jar cleared: a request that
        # instead offers the id via query string and header must not reach
        # the Cart that id names.
        client.cookies.clear()
        response = client.get(
            "/api/cart",
            params={"sessionId": session_cookie},
            headers={"X-Session-Id": session_cookie},
        )

    assert response.json()["items"] == []


# -- Route tests: POST /api/cart/items -------------------------------------


def test_post_item_adds_a_line_priced_from_the_catalogue() -> None:
    with _client() as client:
        response = client.post(
            "/api/cart/items", json={"productId": "p-python", "quantity": 2}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [
        {
            "productId": "p-python",
            "name": "Python Fundamentals",
            "unitPriceMinor": 1999,
            "quantity": 2,
            "subtotalMinor": 3998,
        }
    ]
    assert body["totalMinor"] == 3998
    assert body["currency"] == "USD"


def test_post_unknown_product_returns_404() -> None:
    with _client() as client:
        response = client.post(
            "/api/cart/items", json={"productId": "does-not-exist", "quantity": 1}
        )

    assert response.status_code == 404


@pytest.mark.parametrize("quantity", [0, -1])
def test_post_quantity_below_one_returns_422(quantity: int) -> None:
    with _client() as client:
        response = client.post(
            "/api/cart/items", json={"productId": "p-python", "quantity": quantity}
        )

    assert response.status_code == 422


def test_post_same_product_twice_increments_the_existing_line() -> None:
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 2})
        response = client.post(
            "/api/cart/items", json={"productId": "p-python", "quantity": 3}
        )

    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5


def test_post_rejects_a_client_supplied_price() -> None:
    with _client() as client:
        response = client.post(
            "/api/cart/items",
            json={"productId": "p-python", "quantity": 1, "unitPriceMinor": 1},
        )

    assert response.status_code == 422
    assert "unitPriceMinor" in response.text


# The cumulative-quantity ceiling is `RedisCartRepository`'s own rule, not
# part of the `CartRepository` Protocol — `InMemoryRepository` (BE-02) has
# no notion of it, so a fake-backed route test cannot exercise it. See
# `test_post_cumulative_quantity_over_the_ceiling_returns_422` in the
# Redis-backed route tests below, where it belongs.


# -- Route tests: PATCH /api/cart/items/{productId} ------------------------


def test_patch_sets_the_quantity_of_an_existing_line() -> None:
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 1})
        response = client.patch("/api/cart/items/p-python", json={"quantity": 7})

    assert response.status_code == 200
    assert response.json()["items"][0]["quantity"] == 7


@pytest.mark.parametrize("quantity", [0, -1])
def test_patch_quantity_below_one_returns_422_removal_is_delete(quantity: int) -> None:
    """Deliberately stricter than the domain `set_quantity`, which allows 0."""
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 1})
        response = client.patch("/api/cart/items/p-python", json={"quantity": quantity})

    assert response.status_code == 422


def test_patch_unknown_product_returns_404() -> None:
    with _client() as client:
        response = client.patch("/api/cart/items/does-not-exist", json={"quantity": 3})

    assert response.status_code == 404


def test_patch_rejects_a_client_supplied_price() -> None:
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 1})
        response = client.patch(
            "/api/cart/items/p-python", json={"quantity": 2, "price": 1}
        )

    assert response.status_code == 422


# -- Route tests: DELETE /api/cart/items/{productId} ------------------------


def test_delete_removes_an_existing_line() -> None:
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 1})
        client.post("/api/cart/items", json={"productId": "p-rust", "quantity": 1})

        response = client.delete("/api/cart/items/p-python")

    assert response.status_code == 200
    ids = [item["productId"] for item in response.json()["items"]]
    assert ids == ["p-rust"]


def test_delete_of_an_absent_product_is_a_noop_200_not_404() -> None:
    with _client() as client:
        response = client.delete("/api/cart/items/does-not-exist")

    assert response.status_code == 200
    assert response.json()["items"] == []


# -- Route tests: totals, catalogue re-reads, isolation ---------------------


def test_totals_are_exact_under_integer_arithmetic() -> None:
    with _client() as client:
        client.post("/api/cart/items", json={"productId": "p-python", "quantity": 3})
        response = client.post(
            "/api/cart/items", json={"productId": "p-algebra", "quantity": 5}
        )

    body = response.json()
    # 3 * 1999 + 5 * 999 = 5997 + 4995 = 10992, plain integer addition.
    assert body["totalMinor"] == 10992
    assert isinstance(body["totalMinor"], int)


# `InMemoryRepository`'s `Cart` embeds the actual `Product` object it was
# built with at write time (see `app.domain.cart`'s module docstring) and
# `get_cart` returns that stored `Cart` unchanged, so a catalogue mutation
# after the fact is invisible to it — that is a property of the fake, not
# of the `CartRepository` Protocol. The "re-read on every response" and
# "vanished product is dropped, not a 500" guarantees are specific to
# `RedisCartRepository` (it stores only `{productId: quantity}` and always
# resolves fresh — see its module docstring), so exercising them through
# the HTTP layer needs the real thing: see
# `test_catalogue_price_change_is_reflected_in_an_existing_cart` and
# `test_product_removed_from_catalogue_is_dropped_not_500` in the
# Redis-backed route tests below.


def test_carts_are_isolated_per_session() -> None:
    with _client([PYTHON_BOOK]) as client:
        first = client.post(
            "/api/cart/items", json={"productId": "p-python", "quantity": 1}
        )
        first_session_cookie = first.cookies["session_id"]

        # A second, cookie-less client talking to the same app must not see
        # the first Shopper's Cart.
        with TestClient(app) as second_client:
            second = second_client.get("/api/cart")
            assert second.json()["items"] == []
            assert second.cookies.get("session_id") != first_session_cookie


# -- Protocol conformance ----------------------------------------------------


def test_redis_cart_repository_satisfies_cart_repository_protocol() -> None:
    # `Redis.from_url` does not connect eagerly, so this needs no reachable
    # Redis at all — it only asserts the Protocol's method shape is met.
    unconnected_client = Redis.from_url(
        "redis://localhost:56379/0", decode_responses=True
    )
    repository = RedisCartRepository(unconnected_client, _catalogue(), ttl_seconds=60)

    assert isinstance(repository, CartRepository)


# ============================================================================
# Repository tests: RedisCartRepository against a real Redis
# ============================================================================


def _with_db_index(url: str, db_index: int) -> str:
    """Returns `url` pointed at a different logical Redis database."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db_index}"))


# A distinct database index from the one `REDIS_URL` (and `app.session`'s
# tests) use, so this module's keys never collide with another agent's
# concurrent test run against the same shared Redis instance.
_CART_TEST_DB_INDEX = 5
_CART_TEST_REDIS_URL = _with_db_index(
    os.environ.get("REDIS_URL", "redis://localhost:6379/0"), _CART_TEST_DB_INDEX
)


@pytest.fixture(name="redis_client")
def redis_client_fixture() -> Iterator[Redis]:
    client = Redis.from_url(
        _CART_TEST_REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    except RedisError as exc:
        pytest.skip(f"Redis is not reachable at {_CART_TEST_REDIS_URL}: {exc}")

    try:
        yield client
    finally:
        client.close()


def _session_id() -> str:
    """A session id unique to one test, so parallel test runs never collide."""
    return f"test-cart-{uuid4().hex}"


# -- Route tests backed by the real RedisCartRepository ----------------------
#
# The three behaviours below are specific to `RedisCartRepository` (see the
# comment above `test_carts_are_isolated_per_session`), so exercising them
# through the actual HTTP routes needs the real repository, not
# `InMemoryRepository`, behind `get_cart_repository`.


def test_post_cumulative_quantity_over_the_ceiling_returns_422(
    redis_client: Redis,
) -> None:
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)
    session_id = None
    try:
        with _ClientWithRepository(repository) as client:
            client.post(
                "/api/cart/items",
                json={"productId": "p-python", "quantity": MAX_LINE_ITEM_QUANTITY},
            )
            response = client.post(
                "/api/cart/items", json={"productId": "p-python", "quantity": 1}
            )
            session_id = client.cookies.get("session_id")

        assert response.status_code == 422
    finally:
        if session_id:
            redis_client.delete(f"cart:{session_id}")


def test_catalogue_price_change_is_reflected_in_an_existing_cart(
    redis_client: Redis,
) -> None:
    catalogue = _catalogue([PYTHON_BOOK])
    repository = RedisCartRepository(redis_client, catalogue, ttl_seconds=60)
    session_id = None
    try:
        with _ClientWithRepository(repository) as client:
            client.post(
                "/api/cart/items", json={"productId": "p-python", "quantity": 2}
            )

            # Simulate a catalogue price change between requests: nothing
            # about this Cart's stored state changes (Redis only ever held
            # `{"p-python": 2}`), only what the catalogue now resolves
            # "p-python" to.
            catalogue._products["p-python"] = _product(
                "p-python", "Python Fundamentals", 2499
            )

            response = client.get("/api/cart")
            session_id = client.cookies.get("session_id")

        body = response.json()
        assert body["items"][0]["unitPriceMinor"] == 2499
        assert body["items"][0]["subtotalMinor"] == 4998
        assert body["totalMinor"] == 4998
    finally:
        if session_id:
            redis_client.delete(f"cart:{session_id}")


def test_product_removed_from_catalogue_is_dropped_not_500(
    redis_client: Redis,
) -> None:
    catalogue = _catalogue([PYTHON_BOOK, RUST_BOOK])
    repository = RedisCartRepository(redis_client, catalogue, ttl_seconds=60)
    session_id = None
    try:
        with _ClientWithRepository(repository) as client:
            client.post(
                "/api/cart/items", json={"productId": "p-python", "quantity": 1}
            )
            client.post("/api/cart/items", json={"productId": "p-rust", "quantity": 1})

            del catalogue._products["p-python"]

            response = client.get("/api/cart")
            session_id = client.cookies.get("session_id")

        assert response.status_code == 200
        ids = [item["productId"] for item in response.json()["items"]]
        assert ids == ["p-rust"]
    finally:
        if session_id:
            redis_client.delete(f"cart:{session_id}")


def test_repo_add_item_persists_and_get_cart_reads_it_back(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 2)
        cart = repository.get_cart(session_id)

        assert len(cart.items) == 1
        assert cart.items[0].product.id == "p-python"
        assert cart.items[0].quantity == 2
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_add_item_increments_rather_than_duplicates(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 2)
        cart = repository.add_item(session_id, "p-python", 3)

        assert len(cart.items) == 1
        assert cart.items[0].quantity == 5
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_add_item_unknown_product_raises(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        with pytest.raises(UnknownProductError):
            repository.add_item(session_id, "does-not-exist", 1)
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_add_item_rejects_non_positive_quantity(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        with pytest.raises(ValueError):
            repository.add_item(session_id, "p-python", 0)
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_add_item_over_the_ceiling_raises_value_error(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", MAX_LINE_ITEM_QUANTITY)
        with pytest.raises(ValueError):
            repository.add_item(session_id, "p-python", 1)
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_set_quantity_zero_removes_the_line_and_deletes_the_key(
    redis_client: Redis,
) -> None:
    session_id = _session_id()
    key = f"cart:{session_id}"
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 3)
        assert redis_client.exists(key) == 1

        cart = repository.set_quantity(session_id, "p-python", 0)

        assert cart.items == ()
        assert redis_client.exists(key) == 0
    finally:
        redis_client.delete(key)


def test_repo_set_quantity_negative_raises_value_error(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        with pytest.raises(ValueError):
            repository.set_quantity(session_id, "p-python", -1)
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_remove_item_absent_is_a_noop(redis_client: Redis) -> None:
    session_id = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 1)
        cart = repository.remove_item(session_id, "does-not-exist")

        assert len(cart.items) == 1
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_only_product_id_and_quantity_are_persisted(redis_client: Redis) -> None:
    """Never a name, price, or currency — see the module docstring."""
    session_id = _session_id()
    key = f"cart:{session_id}"
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 2)

        raw = redis_client.get(key)
        assert raw is not None
        stored = json.loads(raw)

        assert stored == {"p-python": 2}
    finally:
        redis_client.delete(key)


def test_repo_catalogue_price_change_is_reflected_in_an_existing_cart(
    redis_client: Redis,
) -> None:
    session_id = _session_id()
    catalogue = _catalogue([PYTHON_BOOK])
    repository = RedisCartRepository(redis_client, catalogue, ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 2)

        catalogue._products["p-python"] = _product(
            "p-python", "Python Fundamentals", 2499
        )
        cart = repository.get_cart(session_id)

        assert cart.items[0].product.price_minor == 2499
        assert cart.subtotal_minor == 4998
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_product_deleted_from_catalogue_is_dropped_not_raised(
    redis_client: Redis,
) -> None:
    session_id = _session_id()
    catalogue = _catalogue([PYTHON_BOOK, RUST_BOOK])
    repository = RedisCartRepository(redis_client, catalogue, ttl_seconds=60)

    try:
        repository.add_item(session_id, "p-python", 1)
        repository.add_item(session_id, "p-rust", 1)

        del catalogue._products["p-python"]
        cart = repository.get_cart(session_id)

        assert [item.product.id for item in cart.items] == ["p-rust"]
    finally:
        redis_client.delete(f"cart:{session_id}")


def test_repo_carts_are_isolated_per_session(redis_client: Redis) -> None:
    session_a = _session_id()
    session_b = _session_id()
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=60)

    try:
        repository.add_item(session_a, "p-python", 1)
        cart_b = repository.get_cart(session_b)

        assert cart_b.items == ()
    finally:
        redis_client.delete(f"cart:{session_a}", f"cart:{session_b}")


def test_repo_sliding_ttl_is_refreshed_on_write_and_on_read(
    redis_client: Redis,
) -> None:
    session_id = _session_id()
    key = f"cart:{session_id}"
    repository = RedisCartRepository(redis_client, _catalogue(), ttl_seconds=4)

    try:
        repository.add_item(session_id, "p-python", 1)
        ttl_after_write = redis_client.ttl(key)

        time.sleep(2)
        ttl_before_read = redis_client.ttl(key)

        repository.get_cart(session_id)
        ttl_after_read = redis_client.ttl(key)

        assert 3 <= ttl_after_write <= 4
        assert 1 <= ttl_before_read <= 2
        assert 3 <= ttl_after_read <= 4
    finally:
        redis_client.delete(key)
