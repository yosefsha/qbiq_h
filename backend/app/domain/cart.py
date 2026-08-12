"""Cart domain types: line items and the Cart itself.

A Cart is server-owned and keyed by an anonymous Shopper's opaque session id
(see `docs/adr/ADR-001-server-owned-cart.md`). A `LineItem` embeds the full
`Product` it refers to, rather than duplicating its name/price/currency, so
a rendered Cart never needs a second lookup against `ProductRepository` and
its subtotal is always integer minor-unit arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.catalog import Product


@dataclass(frozen=True)
class LineItem:
    """One Product within a Cart, together with the quantity wanted of it."""

    product: Product
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")

    @property
    def subtotal_minor(self) -> int:
        """This line's price, quantity included, in integer minor units."""
        return self.product.price_minor * self.quantity


@dataclass(frozen=True)
class Cart:
    """The set of Products a Shopper intends to buy."""

    session_id: str
    items: tuple[LineItem, ...] = ()

    @property
    def subtotal_minor(self) -> int:
        """Sum of every line item's subtotal, in integer minor units."""
        return sum(item.subtotal_minor for item in self.items)
