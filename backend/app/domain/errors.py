"""Domain-level errors raised by repository implementations.

These are storage-agnostic on purpose: a SQL-backed `ProductRepository`
translates a missing row into `UnknownProductError`, a Redis-backed
`CartRepository` does the same, and callers (route handlers, other business
logic) only ever need to catch these — never a driver-specific exception
such as `sqlalchemy.exc.NoResultFound` or a `redis` error.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all errors raised by domain repositories."""


class UnknownSortKeyError(DomainError):
    """Raised when a `ProductQuery.sort` value names no known ordering.

    `ProductQuery.sort` is typed as `SortKey`, but nothing at runtime stops
    a caller constructing a query with an invalid value (e.g. a raw string
    read from an unvalidated query parameter). Repository implementations
    must raise this rather than silently falling back to a default order or
    crashing with an unrelated `KeyError`/`AttributeError`.
    """

    def __init__(self, sort_key: object) -> None:
        self.sort_key = sort_key
        super().__init__(f"Unknown sort key: {sort_key!r}")


class UnknownProductError(DomainError):
    """Raised when an operation references a product id that does not exist."""

    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        super().__init__(f"Unknown product id: {product_id!r}")
