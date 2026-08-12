"""Cart API routes (BE-07): server-authoritative Cart operations.

Implements exactly the four operations ADR-001 assigns to the server: read
the Cart, add a line, change a line's quantity, and remove a line. Every
route depends on `get_session` (`app.session`) for the Shopper's identity
and never reads the `session_id` cookie itself, and never accepts a session
id from a query parameter or header — ADR-001 rejects that outright, since
it would let any caller read or mutate another Shopper's Cart by guessing
or copying an id.

Route handlers below are plain `def`, not `async def` — deliberately.
`CartRepository` (and this router's `RedisCartRepository`) is a
**synchronous** Protocol (see `app.domain.repositories` and
`app.repositories.redis_cart_repository`), so every Redis call a route
makes here is a blocking one. `get_session`, in contrast, is `async def`.
FastAPI handles that mismatch for you: it awaits async dependencies itself,
then — because the path operation function is `def`, not `async def` —
runs the handler in a worker thread from its threadpool rather than
directly on the event loop. Do not "fix" this by making these handlers
`async def`; that would move every blocking Redis call in this module onto
the event loop itself, stalling every other in-flight request while it
waits on the socket.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from app.api.providers import get_product_repository
from app.domain.cart import Cart
from app.domain.errors import UnknownProductError
from app.domain.repositories import CartRepository, ProductRepository
from app.models import (
    AddCartItemRequest,
    CartLineItemView,
    CartView,
    SetCartItemQuantityRequest,
)
from app.redis_client import get_sync_redis_client
from app.repositories.redis_cart_repository import RedisCartRepository
from app.session import SessionId, get_session
from app.settings import settings

router = APIRouter(prefix="/api/cart", tags=["cart"])

#: Reported on an empty Cart. A Cart carries no currency of its own — every
#: `Product` does (see `app.domain.catalog.Product.currency`) — so an empty
#: Cart has no line to read one from. Every row `app/seed.py` inserts is
#: USD, and nothing in the domain model lets a Shopper choose a different
#: one, so this is the storefront's one real currency today rather than an
#: arbitrary placeholder. If the catalogue ever goes multi-currency, this
#: needs to become real per-Shopper or per-locale configuration instead of
#: a constant.
DEFAULT_CART_CURRENCY = "USD"


# -- Product catalogue -------------------------------------------------------
#
# `RedisCartRepository` depends on the `ProductRepository` *Protocol*, not a
# concrete class (see its module docstring), which is what let this task be
# built in parallel with BE-04's Postgres-backed implementation.
#
# The provider itself is `app.api.providers.get_product_repository` — the same
# key the catalogue router depends on, bound once in `app.main`. It is shared
# rather than per-router on purpose: while each router owned its own provider,
# the catalogue served database primary keys while the Cart resolved a slug of
# the product name, so a `productId` copied from a listing 404'd on
# `POST /api/cart/items`.


def get_cart_repository(
    products: ProductRepository = Depends(get_product_repository),
) -> CartRepository:
    """FastAPI dependency providing the `CartRepository` every route below uses.

    Built per-request from process-wide singletons (the sync Redis client,
    the catalogue repository), so constructing it here is cheap. Routes
    depend on this — never on `RedisCartRepository` directly — so a test
    can swap the whole Cart backing store with a single
    `app.dependency_overrides[get_cart_repository] = ...`, typically to an
    `InMemoryRepository` seeded with whatever products that test needs.
    """
    return RedisCartRepository(
        get_sync_redis_client(), products, settings.session_ttl_seconds
    )


def _translate_domain_errors(operation: Callable[[], Cart]) -> Cart:
    """Runs a `CartRepository` write, translating domain errors to HTTP ones.

    Centralized here rather than duplicated as a `try/except` in every
    route below, which is the same goal a FastAPI
    `app.exception_handler`-registered handler serves. That registration
    lives on the `FastAPI` app instance, though (`app.add_exception_handler`
    has no `APIRouter`-level equivalent), and adding it in `app/main.py`
    would grow that file's diff past the single import + `include_router`
    line this task is scoped to. This module-local helper gets the same
    effect — a thin route, one place that knows about `UnknownProductError`
    and quantity `ValueError`s — without touching `app/main.py`.
    """
    try:
        return operation()
    except UnknownProductError as exc:
        # Raw status codes, matching the convention in `app.middleware`,
        # rather than `fastapi.status` constants — `HTTP_422_UNPROCESSABLE_
        # ENTITY` was renamed to `HTTP_422_UNPROCESSABLE_CONTENT` in a recent
        # Starlette and now warns on every use of the old name.
        raise HTTPException(
            status_code=404, detail=f"Unknown product id: {exc.product_id!r}"
        ) from exc
    except ValueError as exc:
        # Reached for a repository-enforced rule Pydantic cannot express at
        # the boundary, e.g. `add_item`'s *cumulative* per-line ceiling
        # (existing quantity + this request's quantity), which no single
        # request's own `quantity` field can be validated against in
        # isolation.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _to_cart_view(cart: Cart) -> CartView:
    """Renders a domain `Cart` into the wire `CartView`.

    Every price here comes from `item.product`, which the repository
    re-resolved against the catalogue for this call (see
    `RedisCartRepository._render`) — never a value read back from Redis —
    so a catalogue price change is reflected on the very next response for
    an existing Cart, and `total_minor` is exact integer addition with no
    floats or rounding anywhere in the chain.
    """
    line_items = [
        CartLineItemView(
            product_id=item.product.id,
            name=item.product.name,
            unit_price_minor=item.product.price_minor,
            quantity=item.quantity,
            subtotal_minor=item.subtotal_minor,
        )
        for item in cart.items
    ]

    currencies = {item.product.currency for item in cart.items}
    if len(currencies) > 1:
        # Every line is priced by the same catalogue, so a Cart is not
        # supposed to be able to reach this state. Treated as a data-
        # integrity bug rather than a client error: it is left to raise
        # (surfacing as a 500) rather than silently summed as though the
        # currencies were the same unit.
        raise RuntimeError(
            f"Cart {cart.session_id!r} mixes currencies: {sorted(currencies)!r}"
        )
    currency = currencies.pop() if currencies else DEFAULT_CART_CURRENCY

    return CartView(
        items=line_items, total_minor=cart.subtotal_minor, currency=currency
    )


@router.get("", response_model=CartView, response_model_by_alias=True)
def get_cart(
    session_id: SessionId = Depends(get_session),
    cart_repository: CartRepository = Depends(get_cart_repository),
) -> CartView:
    """Returns the current Shopper's Cart, creating an empty one if unseen."""
    cart = cart_repository.get_cart(session_id.value)
    return _to_cart_view(cart)


@router.post("/items", response_model=CartView, response_model_by_alias=True)
def add_item(
    body: AddCartItemRequest,
    session_id: SessionId = Depends(get_session),
    cart_repository: CartRepository = Depends(get_cart_repository),
) -> CartView:
    """Adds `quantity` of a product, incrementing rather than duplicating a
    line that is already in the Cart."""
    cart = _translate_domain_errors(
        lambda: cart_repository.add_item(
            session_id.value, body.product_id, body.quantity
        )
    )
    return _to_cart_view(cart)


@router.patch(
    "/items/{product_id}", response_model=CartView, response_model_by_alias=True
)
def set_item_quantity(
    product_id: str,
    body: SetCartItemQuantityRequest,
    session_id: SessionId = Depends(get_session),
    cart_repository: CartRepository = Depends(get_cart_repository),
) -> CartView:
    """Sets a line's quantity to exactly `body.quantity` (always >= 1; see
    `SetCartItemQuantityRequest`)."""
    cart = _translate_domain_errors(
        lambda: cart_repository.set_quantity(
            session_id.value, product_id, body.quantity
        )
    )
    return _to_cart_view(cart)


@router.delete(
    "/items/{product_id}", response_model=CartView, response_model_by_alias=True
)
def remove_item(
    product_id: str,
    session_id: SessionId = Depends(get_session),
    cart_repository: CartRepository = Depends(get_cart_repository),
) -> CartView:
    """Removes a line from the Cart. A no-op, not a 404, if it was absent."""
    cart = cart_repository.remove_item(session_id.value, product_id)
    return _to_cart_view(cart)
