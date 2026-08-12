"""Domain vocabulary and repository Protocols for the storefront.

Everything exported from this package is storage-agnostic — no SQLAlchemy
expression, ORM row, or Redis key may appear in any name here. That is what
lets `app.domain.fakes.InMemoryRepository` satisfy `ProductRepository` and
`CartRepository` without a database, and it is what every other backend
layer (routes, SQL repositories, the Redis cart repository) codes against.

Terms match `CONTEXT.md`: Product, Category, Review, Shopper, Cart, Line
Item.
"""

from __future__ import annotations

from app.domain.cart import Cart, LineItem
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
from app.domain.errors import DomainError, UnknownProductError, UnknownSortKeyError
from app.domain.repositories import CartRepository, ProductRepository

__all__ = [
    "Cart",
    "CartRepository",
    "Category",
    "DomainError",
    "LineItem",
    "Product",
    "ProductDetail",
    "ProductPage",
    "ProductQuery",
    "ProductRepository",
    "Review",
    "SortDirection",
    "SortKey",
    "UnknownProductError",
    "UnknownSortKeyError",
]
