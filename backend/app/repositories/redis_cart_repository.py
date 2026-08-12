"""Redis-backed `CartRepository` (BE-07).

Storage is deliberately minimal: `cart:{sessionId}` holds a JSON object of
`{productId: quantity}` and nothing else — never a name, price, or
currency. Every read and write re-resolves each line against
`ProductRepository`, which is what makes a catalogue price change visible
in an existing Cart (the issue's explicit requirement) and makes a stale
serialized price impossible to serve, since none is ever stored.

`ProductRepository` is injected as the Protocol from
`app.domain.repositories`, not a concrete class, so this module stays
independent of BE-04 (the Postgres-backed implementation), which was built
in parallel. `InMemoryRepository` satisfies the same Protocol, which is
what lets the route tests in `tests/test_cart_api.py` exercise this
repository's routes without a real catalogue.
"""

from __future__ import annotations

import json

from redis import Redis

from app.domain.cart import Cart, LineItem
from app.domain.errors import UnknownProductError
from app.domain.repositories import ProductRepository

_CART_KEY_PREFIX = "cart:"

#: Ceiling on a single line's quantity. Nothing in the brief calls for
#: buying more than this of a single digital good, and without a ceiling a
#: single `POST /api/cart/items` with an absurd integer stores an equally
#: absurd value in Redis (and, downstream, in every rendered Cart's total).
#: Raising `ValueError` here — rather than clamping — matches the domain
#: Protocol's existing convention for a malformed quantity, and the HTTP
#: layer maps it to 422 the same way it maps a `quantity <= 0`.
MAX_LINE_ITEM_QUANTITY = 1_000


def _cart_key(session_id: str) -> str:
    """The Redis key holding `session_id`'s Cart."""
    return f"{_CART_KEY_PREFIX}{session_id}"


def _enforce_quantity_ceiling(quantity: int) -> None:
    if quantity > MAX_LINE_ITEM_QUANTITY:
        raise ValueError(
            f"quantity must be <= {MAX_LINE_ITEM_QUANTITY} (got {quantity})"
        )


class RedisCartRepository:
    """`CartRepository` backed by Redis, satisfying the Protocol structurally.

    Reads and writes go through a **synchronous** `redis.Redis` client (see
    `app.redis_client.get_sync_redis_client`) because `CartRepository` in
    `app.domain.repositories` is a synchronous Protocol, kept that way so
    `InMemoryRepository` (BE-02, already merged) never had to become async.
    """

    def __init__(
        self,
        redis: Redis,
        products: ProductRepository,
        ttl_seconds: int,
    ) -> None:
        self._redis = redis
        self._products = products
        self._ttl_seconds = ttl_seconds

    # -- CartRepository -----------------------------------------------------

    def get_cart(self, session_id: str) -> Cart:
        quantities = self._read_quantities(session_id)
        return self._render(session_id, quantities)

    def add_item(self, session_id: str, product_id: str, quantity: int) -> Cart:
        if quantity <= 0:
            raise ValueError("quantity must be > 0")

        self._require_product(product_id)
        quantities = self._read_quantities(session_id)
        new_quantity = quantities.get(product_id, 0) + quantity
        _enforce_quantity_ceiling(new_quantity)
        quantities[product_id] = new_quantity
        self._write_quantities(session_id, quantities)
        return self._render(session_id, quantities)

    def set_quantity(self, session_id: str, product_id: str, quantity: int) -> Cart:
        if quantity < 0:
            raise ValueError("quantity must be >= 0")

        quantities = self._read_quantities(session_id)
        if quantity == 0:
            quantities.pop(product_id, None)
        else:
            self._require_product(product_id)
            _enforce_quantity_ceiling(quantity)
            quantities[product_id] = quantity
        self._write_quantities(session_id, quantities)
        return self._render(session_id, quantities)

    def remove_item(self, session_id: str, product_id: str) -> Cart:
        quantities = self._read_quantities(session_id)
        quantities.pop(product_id, None)
        self._write_quantities(session_id, quantities)
        return self._render(session_id, quantities)

    # -- storage --------------------------------------------------------

    def _read_quantities(self, session_id: str) -> dict[str, int]:
        """Reads the stored `{productId: quantity}` map, sliding the TTL.

        Absent, this returns an empty map rather than writing anything —
        an unopened Cart never touches Redis, matching
        `InMemoryRepository.get_cart`, which never populates its dict
        until the first write either.
        """
        key = _cart_key(session_id)
        raw = self._redis.get(key)
        if raw is None:
            return {}
        # Sliding TTL: a read is as much "activity" as a write, so a Shopper
        # who is only looking at their Cart does not have it expire out from
        # under them mid-session.
        self._redis.expire(key, self._ttl_seconds)
        data = json.loads(raw)
        return {str(product_id): int(qty) for product_id, qty in data.items()}

    def _write_quantities(self, session_id: str, quantities: dict[str, int]) -> None:
        """Persists `{productId: quantity}`, or deletes the key once it's empty.

        `SET ... EX` sets the value and a fresh TTL atomically, keeping the
        TTL sliding on writes exactly as it does on reads.
        """
        key = _cart_key(session_id)
        if not quantities:
            self._redis.delete(key)
            return
        self._redis.set(key, json.dumps(quantities), ex=self._ttl_seconds)

    # -- rendering --------------------------------------------------------

    def _render(self, session_id: str, quantities: dict[str, int]) -> Cart:
        """Builds a `Cart` from stored quantities, re-reading every price.

        A product id with no matching row in `ProductRepository` — deleted
        from the catalogue since it was added — is silently dropped from
        the rendered Cart rather than raising, so one vanished product
        does not lock a Shopper out of the rest of their Cart. The
        dangling quantity is left in Redis rather than rewritten here,
        since `_render` backs both write paths (which already persisted
        their own change) and the pure-read `get_cart` (which must not
        turn a read into a write).
        """
        items = []
        for product_id, quantity in quantities.items():
            product = self._products.get_product(product_id)
            if product is None:
                continue
            items.append(LineItem(product=product, quantity=quantity))
        return Cart(session_id=session_id, items=tuple(items))

    def _require_product(self, product_id: str) -> None:
        if self._products.get_product(product_id) is None:
            raise UnknownProductError(product_id)
