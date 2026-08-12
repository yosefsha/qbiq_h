"""Catalogue domain types: categories, products, reviews, and queries.

Frozen dataclasses per `docs/coding-instructions.md` — internal value
objects that don't need Pydantic validation. Prices are always integer
minor units plus an ISO 4217 currency code (see
`docs/adr/ADR-003-managed-aws-data-tier.md`), never a float, so totals
computed downstream stay exact integer arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SortKey(str, Enum):
    """Fields a product listing can be ordered by."""

    NAME = "name"
    PRICE = "price"


class SortDirection(str, Enum):
    """Direction of a product listing sort."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class Category:
    """The kind of digital good a Product is. Every Product has exactly one."""

    slug: str
    name: str


@dataclass(frozen=True)
class Review:
    """A shopper's written verdict on a Product."""

    id: str
    author: str
    rating: int
    body: str

    def __post_init__(self) -> None:
        if not 1 <= self.rating <= 5:
            raise ValueError("rating must be between 1 and 5")


@dataclass(frozen=True)
class Product:
    """A digital good offered for sale — an e-book, a licence, or a course."""

    id: str
    name: str
    price_minor: int
    currency: str
    short_description: str
    thumbnail_url: str
    category: Category


@dataclass(frozen=True)
class ProductDetail(Product):
    """A `Product` plus the extra content shown on its detail page."""

    long_description: str
    reviews: tuple[Review, ...]


#: Largest page a caller may request. The HTTP layer should surface a request
#: above this as a 422 rather than silently clamping, so a client paging with a
#: too-large limit learns it is doing so instead of quietly getting short pages.
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class ProductQuery:
    """Filter, sort, and page parameters for listing the catalogue."""

    name_contains: str | None = None
    category_slug: str | None = None
    sort: SortKey = SortKey.NAME
    direction: SortDirection = SortDirection.ASC
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError("limit must be >= 0")
        if self.limit > MAX_PAGE_SIZE:
            # Enforced here so every implementation inherits the ceiling. The
            # catalogue is public and unauthenticated (ADR-002), so without a
            # bound `?limit=1000000000` becomes an unbounded scan of the
            # products table the moment this query reaches Postgres in BE-04 —
            # cheap for the caller, expensive for the database.
            raise ValueError(f"limit must be <= {MAX_PAGE_SIZE}")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")


@dataclass(frozen=True)
class ProductPage:
    """A page of `Product`s together with the total count matching the query."""

    items: tuple[Product, ...]
    total: int
