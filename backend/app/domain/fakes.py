"""In-memory fake satisfying both `ProductRepository` and `CartRepository`.

This is a deliverable, not a private test helper: BE-04, BE-05 and BE-07
construct it inline in their own tests (per the "unit tests construct
dependencies inline" rule in `docs/coding-instructions.md`) to exercise
business logic without a real Postgres or Redis instance. Protocols are
structural, so `InMemoryRepository` satisfies both without inheriting from
either.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.domain.cart import Cart, LineItem
from app.domain.catalog import (
    Product,
    ProductDetail,
    ProductPage,
    ProductQuery,
    SortDirection,
    SortKey,
)
from app.domain.errors import UnknownProductError, UnknownSortKeyError

_SortFunc = Callable[[Product], "str | int"]

_SORT_FUNCS: dict[SortKey, _SortFunc] = {
    SortKey.NAME: lambda product: product.name.lower(),
    SortKey.PRICE: lambda product: product.price_minor,
}


class InMemoryRepository:
    """A storage-free stand-in for `ProductRepository` and `CartRepository`.

    Holds a fixed product catalogue, seeded at construction, and a mutable,
    in-process map of session id -> Cart.
    """

    def __init__(self, products: Iterable[Product] = ()) -> None:
        self._products: dict[str, Product] = {
            product.id: product for product in products
        }
        self._carts: dict[str, Cart] = {}

    # -- ProductRepository ---------------------------------------------

    def list_products(self, query: ProductQuery) -> ProductPage:
        items = list(self._products.values())

        if query.name_contains:
            needle = query.name_contains.lower()
            items = [product for product in items if needle in product.name.lower()]

        if query.category_slug is not None:
            items = [
                product
                for product in items
                if product.category.slug == query.category_slug
            ]

        try:
            sort_func = _SORT_FUNCS[query.sort]
        except KeyError:
            raise UnknownSortKeyError(query.sort) from None

        items.sort(key=sort_func, reverse=query.direction == SortDirection.DESC)

        total = len(items)
        page = items[query.offset : query.offset + query.limit]
        return ProductPage(items=tuple(page), total=total)

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        """Return the seeded `ProductDetail` for `product_id`, if any.

        Satisfies `ProductRepository.get_product_detail`. Returns `None` for a
        product seeded only as a summary `Product`, matching a storage-backed
        implementation that finds the row but has no detail content for it.
        """
        product = self._products.get(product_id)
        return product if isinstance(product, ProductDetail) else None

    # -- CartRepository ---------------------------------------------------

    def get_cart(self, session_id: str) -> Cart:
        return self._carts.get(session_id, Cart(session_id=session_id))

    def add_item(self, session_id: str, product_id: str, quantity: int) -> Cart:
        if quantity <= 0:
            raise ValueError("quantity must be > 0")

        product = self._require_product(product_id)
        items_by_product = self._items_by_product(session_id)
        existing = items_by_product.get(product_id)
        new_quantity = quantity + (existing.quantity if existing else 0)
        items_by_product[product_id] = LineItem(product=product, quantity=new_quantity)
        return self._save_cart(session_id, items_by_product)

    def set_quantity(self, session_id: str, product_id: str, quantity: int) -> Cart:
        if quantity < 0:
            raise ValueError("quantity must be >= 0")

        items_by_product = self._items_by_product(session_id)
        if quantity == 0:
            items_by_product.pop(product_id, None)
        else:
            product = self._require_product(product_id)
            items_by_product[product_id] = LineItem(product=product, quantity=quantity)
        return self._save_cart(session_id, items_by_product)

    def remove_item(self, session_id: str, product_id: str) -> Cart:
        items_by_product = self._items_by_product(session_id)
        items_by_product.pop(product_id, None)
        return self._save_cart(session_id, items_by_product)

    def _items_by_product(self, session_id: str) -> dict[str, LineItem]:
        cart = self.get_cart(session_id)
        return {item.product.id: item for item in cart.items}

    def _save_cart(
        self, session_id: str, items_by_product: dict[str, LineItem]
    ) -> Cart:
        cart = Cart(session_id=session_id, items=tuple(items_by_product.values()))
        self._carts[session_id] = cart
        return cart

    def _require_product(self, product_id: str) -> Product:
        product = self._products.get(product_id)
        if product is None:
            raise UnknownProductError(product_id)
        return product
