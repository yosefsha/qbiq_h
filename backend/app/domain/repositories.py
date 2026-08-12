"""Repository Protocols every storage-backed implementation codes against.

No SQLAlchemy, ORM row, or Redis type may appear in any signature here —
that constraint is the entire point of the abstraction (see
`docs/adr/ADR-003-managed-aws-data-tier.md`). `ProductRepository` is
satisfied by BE-04's Postgres-backed repository; `CartRepository` is
satisfied by BE-07's Redis-backed repository. Both are also satisfied by
`app.domain.fakes.InMemoryRepository`, so tests never need a real database.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.cart import Cart
from app.domain.catalog import Product, ProductDetail, ProductPage, ProductQuery


@runtime_checkable
class ProductRepository(Protocol):
    """Read access to the product catalogue."""

    def list_products(self, query: ProductQuery) -> ProductPage:
        """Return a page of products matching `query`.

        Raises:
            UnknownSortKeyError: if `query.sort` names no known ordering.
        """
        ...

    def get_product(self, product_id: str) -> Product | None:
        """Return the product with `product_id`, or `None` if it does not exist.

        Returns the summary shape used by list views. For the detail page,
        which additionally needs the long description and reviews, use
        `get_product_detail` rather than downcasting this result.
        """
        ...

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        """Return the full detail for `product_id`, or `None` if absent.

        Part of the Protocol deliberately. `ProductDetail` was previously
        reachable only on the concrete in-memory fake, which forced any caller
        wanting a long description or reviews — that is, BE-05's
        `GET /products/{id}` — either to `isinstance`-downcast the result of
        `get_product` or to type-annotate against the fake. Both defeat the
        storage-agnostic boundary this module exists to draw.

        Implementations should load reviews here and NOT in `list_products`,
        which would otherwise issue a query per row.
        """
        ...


@runtime_checkable
class CartRepository(Protocol):
    """Read/write access to a Shopper's Cart, keyed by session id."""

    def get_cart(self, session_id: str) -> Cart:
        """Return the Cart for `session_id`, creating an empty one if needed."""
        ...

    def add_item(self, session_id: str, product_id: str, quantity: int) -> Cart:
        """Add `quantity` of `product_id` to the Cart, returning the updated Cart.

        Raises:
            UnknownProductError: if `product_id` does not exist.
        """
        ...

    def set_quantity(self, session_id: str, product_id: str, quantity: int) -> Cart:
        """Set the quantity of `product_id` in the Cart to exactly `quantity`.

        A quantity of `0` removes the line item. Returns the updated Cart.

        Raises:
            UnknownProductError: if `product_id` does not exist and `quantity` > 0.
        """
        ...

    def remove_item(self, session_id: str, product_id: str) -> Cart:
        """Remove `product_id` from the Cart, returning the updated Cart.

        A no-op, not an error, if the product was not in the Cart.
        """
        ...
