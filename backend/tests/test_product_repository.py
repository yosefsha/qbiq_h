"""Tests for `SqlProductRepository` (BE-04).

Integration tests against a real Postgres instance reached via
`DATABASE_URL`, following the same pattern as `tests/test_seed.py`: each test
runs inside a SAVEPOINT nested in an outer transaction that is always rolled
back, and the fixture skips gracefully — rather than erroring — if Postgres
is unreachable or the schema has not been migrated. Fixture rows are created
per test rather than depending on `app.seed`'s exact contents, and are always
rolled back, never left behind.

Requires the `postgres` Docker Compose service reachable at `DATABASE_URL`;
see `backend/tests/test_seed.py` for the identical setup rationale.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Category as CategoryRow
from app.db.models import Product as ProductRow
from app.db.models import Review as ReviewRow
from app.db.session import engine
from app.domain.catalog import ProductQuery, SortDirection, SortKey
from app.domain.errors import UnknownSortKeyError
from app.domain.repositories import ProductRepository
from app.repositories.sql_product_repository import SqlProductRepository


@pytest.fixture(name="session")
def session_fixture() -> Iterator[Session]:
    """A session bound to a savepoint inside a transaction that always rolls
    back, so fixture rows created in a test never persist."""
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"Postgres is not reachable at DATABASE_URL: {exc}")

    if not inspect(engine).has_table(ProductRow.__tablename__):
        connection.close()
        pytest.skip(
            "Postgres is reachable but the schema is missing. "
            "Run `alembic upgrade head` from backend/ first."
        )

    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture(name="repository")
def repository_fixture(session: Session) -> SqlProductRepository:
    return SqlProductRepository(session)


class _StatementCounter:
    """Counts SQL statements issued on `session`'s connection via
    `before_cursor_execute`, so "no N+1" is verified by counting, not by
    eyeballing generated SQL."""

    def __init__(self, session: Session) -> None:
        self.count = 0
        self._connection = session.connection()
        event.listen(self._connection, "before_cursor_execute", self._on_execute)

    def _on_execute(self, *_args: object, **_kwargs: object) -> None:
        self.count += 1

    def stop(self) -> None:
        event.remove(self._connection, "before_cursor_execute", self._on_execute)


def _make_category(session: Session, slug: str, label: str) -> CategoryRow:
    category = CategoryRow(slug=slug, label=label)
    session.add(category)
    session.flush()
    return category


def _make_product(
    session: Session,
    category: CategoryRow,
    name: str,
    price_minor: int,
    *,
    short_description: str = "short",
    long_description: str = "long",
    thumbnail_url: str = "https://example.com/thumb.png",
    currency: str = "USD",
) -> ProductRow:
    product = ProductRow(
        name=name,
        price_minor=price_minor,
        currency=currency,
        short_description=short_description,
        long_description=long_description,
        thumbnail_url=thumbnail_url,
        category=category,
    )
    session.add(product)
    session.flush()
    return product


def _make_review(
    session: Session, product: ProductRow, author: str, rating: int, body: str
) -> ReviewRow:
    review = ReviewRow(product=product, author=author, rating=rating, body=body)
    session.add(review)
    session.flush()
    return review


# -- Protocol conformance -------------------------------------------------


def test_sql_product_repository_satisfies_product_repository(
    repository: SqlProductRepository,
) -> None:
    assert isinstance(repository, ProductRepository)


# -- name filter: ILIKE + literal escaping --------------------------------


def test_name_filter_is_case_insensitive_substring(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-1", "E-Books")
    _make_product(session, category, "Python Fundamentals", 1999)
    _make_product(session, category, "Rust in Practice", 2999)
    session.commit()

    # Scoped to this test's own category so pre-existing seed data (which may
    # itself contain "python", e.g. a FastAPI course) cannot leak in — the
    # test must not depend on the seed's exact contents.
    page = repository.list_products(
        ProductQuery(name_contains="PYTHON", category_slug="ebooks-1")
    )

    assert [p.name for p in page.items] == ["Python Fundamentals"]
    assert page.total == 1


def test_name_filter_treats_percent_and_underscore_as_literal(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-2", "E-Books")
    _make_product(session, category, "100% Cotton Guide", 500)
    _make_product(session, category, "1000 Cotton Guide", 600)
    session.commit()

    page = repository.list_products(ProductQuery(name_contains="100%"))

    assert [p.name for p in page.items] == ["100% Cotton Guide"]
    assert page.total == 1

    underscore_page = repository.list_products(ProductQuery(name_contains="10_"))
    assert underscore_page.items == ()
    assert underscore_page.total == 0


def test_name_filter_with_quotes_is_treated_as_a_literal(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-3", "E-Books")
    _make_product(session, category, "O'Reilly's Guide", 700)
    session.commit()

    page = repository.list_products(ProductQuery(name_contains="O'Reilly's"))

    assert [p.name for p in page.items] == ["O'Reilly's Guide"]
    assert page.total == 1

    # Confirms the query still executes safely with `--` and other SQL
    # metacharacters embedded in the needle.
    hostile_page = repository.list_products(
        ProductQuery(name_contains="'; DROP TABLE product--")
    )
    assert hostile_page.items == ()
    assert hostile_page.total == 0


# -- category filter --------------------------------------------------------


def test_category_filter_matches_by_slug(
    session: Session, repository: SqlProductRepository
) -> None:
    ebooks = _make_category(session, "ebooks-4", "E-Books")
    courses = _make_category(session, "courses-4", "Courses")
    _make_product(session, ebooks, "Ebook One", 1000)
    _make_product(session, courses, "Course One", 2000)
    session.commit()

    page = repository.list_products(ProductQuery(category_slug="courses-4"))

    assert [p.name for p in page.items] == ["Course One"]
    assert page.total == 1


# -- filters compose --------------------------------------------------------


def test_name_and_category_filters_compose(
    session: Session, repository: SqlProductRepository
) -> None:
    ebooks = _make_category(session, "ebooks-5", "E-Books")
    courses = _make_category(session, "courses-5", "Courses")
    _make_product(session, ebooks, "Algebra Refresher", 1000)
    _make_product(session, courses, "Algebra Refresher", 2000)
    _make_product(session, courses, "Calculus Refresher", 3000)
    session.commit()

    page = repository.list_products(
        ProductQuery(name_contains="algebra", category_slug="courses-5")
    )

    assert len(page.items) == 1
    assert page.items[0].name == "Algebra Refresher"
    assert page.items[0].category.slug == "courses-5"
    assert page.total == 1


# -- sort: whitelist + hostile values ---------------------------------------


def test_unknown_sort_key_raises_domain_error_and_issues_no_sql(
    session: Session, repository: SqlProductRepository
) -> None:
    session.commit()
    counter = _StatementCounter(session)
    try:
        query = ProductQuery(sort="name; DROP TABLE product--")  # type: ignore[arg-type]

        with pytest.raises(UnknownSortKeyError) as excinfo:
            repository.list_products(query)

        assert excinfo.value.sort_key == "name; DROP TABLE product--"
        assert counter.count == 0
    finally:
        counter.stop()


def test_sort_by_name_ascending(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-6", "E-Books")
    _make_product(session, category, "Zebra Handbook", 1000)
    _make_product(session, category, "Apple Handbook", 2000)
    session.commit()

    page = repository.list_products(
        ProductQuery(
            sort=SortKey.NAME, direction=SortDirection.ASC, category_slug="ebooks-6"
        )
    )

    assert [p.name for p in page.items] == ["Apple Handbook", "Zebra Handbook"]


def test_sort_by_price_descending(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-7", "E-Books")
    _make_product(session, category, "Cheap Item", 100)
    _make_product(session, category, "Pricey Item", 9000)
    session.commit()

    page = repository.list_products(
        ProductQuery(
            sort=SortKey.PRICE, direction=SortDirection.DESC, category_slug="ebooks-7"
        )
    )

    assert [p.name for p in page.items] == ["Pricey Item", "Cheap Item"]


def test_sort_is_deterministic_with_duplicate_names(
    session: Session, repository: SqlProductRepository
) -> None:
    """`name` is not unique, so ties must be broken by primary key rather
    than dropping or repeating rows across pages."""
    category = _make_category(session, "ebooks-8", "E-Books")
    first = _make_product(session, category, "Same Name", 1000)
    second = _make_product(session, category, "Same Name", 1000)
    session.commit()

    page = repository.list_products(
        ProductQuery(sort=SortKey.NAME, category_slug="ebooks-8", limit=10)
    )

    assert [p.id for p in page.items] == sorted(
        [str(first.id), str(second.id)], key=int
    )


# -- list_products: no N+1 ----------------------------------------------


def test_list_products_issues_no_per_row_review_queries(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-9", "E-Books")
    for index in range(5):
        product = _make_product(session, category, f"Product {index}", 1000 + index)
        _make_review(session, product, f"Author {index}", 5, "Great.")
    session.commit()

    counter = _StatementCounter(session)
    try:
        page = repository.list_products(
            ProductQuery(category_slug="ebooks-9", limit=10)
        )
        assert len(page.items) == 5
        # One COUNT and one SELECT — not one per row, and no review query at
        # all, regardless of how many products matched.
        assert counter.count == 2
    finally:
        counter.stop()


# -- pagination -----------------------------------------------------------


def test_pagination_pages_are_disjoint_and_total_is_stable(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-10", "E-Books")
    for index in range(5):
        _make_product(session, category, f"Item {index:02d}", 1000 + index)
    session.commit()

    first_page = repository.list_products(
        ProductQuery(category_slug="ebooks-10", limit=2, offset=0)
    )
    second_page = repository.list_products(
        ProductQuery(category_slug="ebooks-10", limit=2, offset=2)
    )
    third_page = repository.list_products(
        ProductQuery(category_slug="ebooks-10", limit=2, offset=4)
    )

    assert first_page.total == 5
    assert second_page.total == 5
    assert third_page.total == 5

    first_ids = {p.id for p in first_page.items}
    second_ids = {p.id for p in second_page.items}
    third_ids = {p.id for p in third_page.items}
    assert first_ids.isdisjoint(second_ids)
    assert second_ids.isdisjoint(third_ids)
    assert first_ids.isdisjoint(third_ids)
    assert len(first_ids | second_ids | third_ids) == 5


def test_pagination_offset_beyond_total_is_empty(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-11", "E-Books")
    _make_product(session, category, "Only Item", 1000)
    session.commit()

    page = repository.list_products(
        ProductQuery(category_slug="ebooks-11", limit=10, offset=100)
    )

    assert page.items == ()
    assert page.total == 1


# -- get_product ------------------------------------------------------------


def test_get_product_returns_matching_product(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-12", "E-Books")
    product = _make_product(session, category, "Findable Product", 1234)
    session.commit()

    result = repository.get_product(str(product.id))

    assert result is not None
    assert result.name == "Findable Product"
    assert result.price_minor == 1234
    assert result.category.slug == "ebooks-12"
    assert result.category.name == "E-Books"


def test_get_product_returns_none_for_non_numeric_id(
    repository: SqlProductRepository,
) -> None:
    assert repository.get_product("not-a-number") is None


def test_get_product_returns_none_for_absent_id(
    repository: SqlProductRepository,
) -> None:
    assert repository.get_product("999999999") is None


def test_get_product_returns_none_for_out_of_int4_range_id(
    repository: SqlProductRepository,
) -> None:
    assert repository.get_product("99999999999999999999") is None


# -- get_product_detail -------------------------------------------------


def test_get_product_detail_returns_reviews_and_long_description(
    session: Session, repository: SqlProductRepository
) -> None:
    category = _make_category(session, "ebooks-13", "E-Books")
    product = _make_product(
        session,
        category,
        "Detailed Product",
        4321,
        long_description="A much longer description.",
    )
    _make_review(session, product, "Ana", 5, "Loved it.")
    _make_review(session, product, "Ben", 3, "It was fine.")
    session.commit()

    detail = repository.get_product_detail(str(product.id))

    assert detail is not None
    assert detail.long_description == "A much longer description."
    assert {review.author for review in detail.reviews} == {"Ana", "Ben"}
    assert {review.rating for review in detail.reviews} == {5, 3}


def test_get_product_detail_returns_none_for_absent_id(
    repository: SqlProductRepository,
) -> None:
    assert repository.get_product_detail("999999999") is None


def test_get_product_detail_returns_none_for_non_numeric_id(
    repository: SqlProductRepository,
) -> None:
    assert repository.get_product_detail("abc") is None


# -- list_categories (BE-05) -------------------------------------------------


def test_list_categories_returns_every_category_ordered_by_slug(
    session: Session, repository: SqlProductRepository
) -> None:
    _make_category(session, "zzz-cat-1", "Zzz Category")
    _make_category(session, "aaa-cat-1", "Aaa Category")
    session.commit()

    categories = repository.list_categories()
    slugs = [category.slug for category in categories]

    # Scoped assertion: other tests and the seed may add categories of their
    # own, so this checks relative order among the ones this test created
    # rather than asserting the full list.
    assert slugs.index("aaa-cat-1") < slugs.index("zzz-cat-1")


def test_list_categories_maps_label_column_to_domain_name_field(
    session: Session, repository: SqlProductRepository
) -> None:
    _make_category(session, "mapped-cat-1", "Mapped Category")
    session.commit()

    categories = repository.list_categories()

    match = next(c for c in categories if c.slug == "mapped-cat-1")
    assert match.name == "Mapped Category"
