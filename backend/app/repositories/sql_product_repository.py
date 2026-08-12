"""Postgres-backed `ProductRepository` (BE-04).

Satisfies `app.domain.repositories.ProductRepository` against the schema in
`app.db.models`. No ORM row or SQLAlchemy type ever escapes this module —
every public method returns a domain dataclass from `app.domain.catalog`, or
`None`, matching the storage-agnostic boundary the Protocol exists to draw.

Synchronous by design: the Protocol methods are synchronous and
`app.db.session.SessionLocal` yields a plain `sqlalchemy.orm.Session`, so this
class takes one in its constructor rather than building its own engine or
opening its own transactions — that stays the caller's responsibility (a
route handler's request-scoped session in BE-05, or a test fixture here).

Two mapping decisions worth calling out explicitly:

1. Id type. `product.id` and `review.id` are Postgres `integer` primary keys;
   the domain models them as `str` (`Product.id`, `Review.id`). Going out,
   `str(row.id)` is always safe. Coming in (`get_product`,
   `get_product_detail`), a caller-supplied id may not even be numeric — e.g.
   `get_product("abc")` — and hitting Postgres with that would surface as a
   driver-level `InvalidTextRepresentation` / `DataError`, which is exactly
   the kind of storage exception a domain-layer caller must never see. So the
   id is parsed and range-checked in Python first; anything that is not a
   valid `int32` short-circuits to `None` before any SQL is issued.
2. Category naming. The `category` table's descriptive column is named
   `label`; the domain field is `Category.name`. `_to_category` is the single
   place that crosses that naming boundary.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, contains_eager, selectinload

from app.db.models import Category as CategoryRow
from app.db.models import Product as ProductRow
from app.db.models import Review as ReviewRow
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

# Explicit whitelist: the only two columns a `ProductQuery.sort` may resolve
# to. A sort key is looked up here and never interpolated into SQL text, so
# an unrecognised or hostile value (e.g. "name; DROP TABLE product--") simply
# misses this dict and raises `UnknownSortKeyError` before any statement is
# built. `SortKey` is a `str` Enum, so a plain string value (as arrives from
# an unvalidated query parameter) hashes and compares equal to its member,
# same as the lookup in `app.domain.fakes.InMemoryRepository`.
_SORT_COLUMNS: dict[SortKey, Any] = {
    SortKey.NAME: ProductRow.name,
    SortKey.PRICE: ProductRow.price_minor,
}

# Postgres `integer` (int4) bounds. A caller-supplied id outside this range
# is guaranteed not to match any row, so it is treated the same as a
# non-numeric id (see decision 1 above) rather than being sent to the driver.
_INT4_MIN = -2_147_483_648
_INT4_MAX = 2_147_483_647


def _escape_like(needle: str) -> str:
    """Escapes `\\`, `%`, and `_` so `needle` is matched as a literal substring.

    Backslash is escaped first so the escaping of `%`/`_` does not itself
    introduce a second, unescaped backslash.
    """
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_product_id(product_id: str) -> int | None:
    """Parses a domain product id into the integer primary key, or `None`.

    `None` covers both a non-numeric id and one outside Postgres `int4`
    range — either way, no row could possibly match, so this returns `None`
    rather than letting an invalid id reach SQL.
    """
    try:
        pk = int(product_id)
    except (TypeError, ValueError):
        return None
    if not (_INT4_MIN <= pk <= _INT4_MAX):
        return None
    return pk


def _to_category(row: CategoryRow) -> Category:
    # `category.label` (DB) -> `Category.name` (domain) — decision 2 above.
    return Category(slug=row.slug, name=row.label)


def _to_review(row: ReviewRow) -> Review:
    return Review(id=str(row.id), author=row.author, rating=row.rating, body=row.body)


def _to_product(row: ProductRow) -> Product:
    return Product(
        id=str(row.id),
        name=row.name,
        price_minor=row.price_minor,
        currency=row.currency,
        short_description=row.short_description,
        thumbnail_url=row.thumbnail_url,
        category=_to_category(row.category),
    )


def _to_product_detail(row: ProductRow) -> ProductDetail:
    # Reviews are sorted by id for a deterministic order: `selectinload` does
    # not guarantee row order, and the domain type makes no ordering promise
    # of its own, but a stable order still makes callers (and tests) able to
    # rely on it rather than on incidental DB return order.
    reviews = tuple(
        _to_review(review) for review in sorted(row.reviews, key=lambda r: r.id)
    )
    return ProductDetail(
        id=str(row.id),
        name=row.name,
        price_minor=row.price_minor,
        currency=row.currency,
        short_description=row.short_description,
        thumbnail_url=row.thumbnail_url,
        category=_to_category(row.category),
        long_description=row.long_description,
        reviews=reviews,
    )


class SqlProductRepository:
    """`ProductRepository` implementation backed by a SQLAlchemy `Session`.

    Holds no engine and opens no transaction of its own — it reads through
    whatever `Session` it is given, so the caller controls transaction and
    connection lifetime (see `app.db.session.SessionLocal`).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- ProductRepository ---------------------------------------------

    def list_products(self, query: ProductQuery) -> ProductPage:
        """Returns a page of products matching `query`.

        Issues exactly two statements regardless of page size: one `COUNT`
        over the filtered set and one bounded `SELECT` for the page itself.
        Category is loaded via the same join with `contains_eager` so
        `product.category` needs no extra query per row; reviews are never
        touched here, per the Protocol's no-N+1 requirement.
        """
        try:
            sort_column = _SORT_COLUMNS[query.sort]
        except KeyError:
            raise UnknownSortKeyError(query.sort) from None

        filtered = self._filtered_products(query)

        total = self._session.execute(
            select(func.count()).select_from(filtered.subquery())
        ).scalar_one()

        order_column = (
            sort_column.desc()
            if query.direction == SortDirection.DESC
            else sort_column.asc()
        )
        # `name` is not unique in the schema (see `app/db/models.py`), so the
        # primary key is added as a tiebreaker. Without it, rows tied on the
        # sort column could be dropped or repeated across pages depending on
        # how Postgres happens to order ties.
        items_stmt = (
            filtered.options(contains_eager(ProductRow.category))
            .order_by(order_column, ProductRow.id.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        rows = self._session.execute(items_stmt).scalars().all()
        return ProductPage(items=tuple(_to_product(row) for row in rows), total=total)

    def get_product(self, product_id: str) -> Product | None:
        """Returns the summary `Product` for `product_id`, or `None`."""
        pk = _parse_product_id(product_id)
        if pk is None:
            return None

        stmt = (
            select(ProductRow)
            .join(ProductRow.category)
            .options(contains_eager(ProductRow.category))
            .where(ProductRow.id == pk)
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return _to_product(row) if row is not None else None

    def get_product_detail(self, product_id: str) -> ProductDetail | None:
        """Returns the full `ProductDetail` for `product_id`, or `None`.

        Reviews are loaded here, via `selectinload` (a bounded, second
        query), and nowhere else — `list_products` never touches them.
        """
        pk = _parse_product_id(product_id)
        if pk is None:
            return None

        stmt = (
            select(ProductRow)
            .join(ProductRow.category)
            .options(
                contains_eager(ProductRow.category),
                selectinload(ProductRow.reviews),
            )
            .where(ProductRow.id == pk)
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return _to_product_detail(row) if row is not None else None

    def list_categories(self) -> tuple[Category, ...]:
        """Returns every `Category`, ordered by `slug` for a deterministic
        listing.

        A single, unbounded `SELECT` — the category table is small and
        expected to stay so (it is edited by catalogue maintainers, not
        Shoppers), so no paging is offered here.
        """
        stmt = select(CategoryRow).order_by(CategoryRow.slug.asc())
        rows = self._session.execute(stmt).scalars().all()
        return tuple(_to_category(row) for row in rows)

    # -- internals ------------------------------------------------------

    def _filtered_products(self, query: ProductQuery):
        """Builds the filtered-but-unordered `SELECT`, shared by the count
        query and the page query in `list_products` so both see identical
        filters."""
        stmt = select(ProductRow).join(ProductRow.category)

        if query.name_contains:
            pattern = f"%{_escape_like(query.name_contains)}%"
            stmt = stmt.where(ProductRow.name.ilike(pattern, escape="\\"))

        if query.category_slug is not None:
            stmt = stmt.where(CategoryRow.slug == query.category_slug)

        return stmt
