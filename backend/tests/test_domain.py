"""Tests for the domain types and the in-memory repository fake.

Covers filtering, sorting (including the unknown-sort-key domain error),
pagination, and Cart quantity arithmetic in integer minor units — the
behaviour the "Done when" checklist on BE-02 requires.
"""

from __future__ import annotations

import pytest

from app.domain.cart import Cart, LineItem
from app.domain.catalog import (
    MAX_PAGE_SIZE,
    Category,
    Product,
    ProductDetail,
    ProductQuery,
    Review,
    SortDirection,
    SortKey,
)
from app.domain.errors import UnknownProductError, UnknownSortKeyError
from app.domain.fakes import InMemoryRepository
from app.domain.repositories import CartRepository, ProductRepository

EBOOKS = Category(slug="ebooks", name="E-books")
COURSES = Category(slug="courses", name="Courses")


def _product(
    product_id: str,
    name: str,
    price_minor: int,
    category: Category = EBOOKS,
) -> Product:
    return Product(
        id=product_id,
        name=name,
        price_minor=price_minor,
        currency="USD",
        short_description=f"{name} short description",
        thumbnail_url=f"https://example.com/{product_id}.png",
        category=category,
    )


def _repository() -> InMemoryRepository:
    return InMemoryRepository(
        products=[
            _product("p-python", "Python Fundamentals", 1999, EBOOKS),
            _product("p-rust", "Rust in Practice", 2999, EBOOKS),
            _product("p-algebra", "Algebra Refresher", 999, COURSES),
            _product("p-calculus", "Calculus Refresher", 1499, COURSES),
        ]
    )


# -- Protocol conformance -----------------------------------------------


def test_in_memory_repository_satisfies_both_protocols() -> None:
    repository = _repository()

    assert isinstance(repository, ProductRepository)
    assert isinstance(repository, CartRepository)


# -- ProductQuery / ProductPage invariants -------------------------------


def test_product_query_rejects_negative_limit() -> None:
    with pytest.raises(ValueError):
        ProductQuery(limit=-1)


def test_product_query_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        ProductQuery(offset=-1)


# -- list_products: filtering ---------------------------------------------


def test_list_products_filters_by_name_contains() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(name_contains="refresher"))

    assert {product.id for product in page.items} == {"p-algebra", "p-calculus"}
    assert page.total == 2


def test_list_products_filters_by_category_slug() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(category_slug="courses"))

    assert {product.id for product in page.items} == {"p-algebra", "p-calculus"}
    assert page.total == 2


def test_list_products_with_no_matches_returns_empty_page() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(name_contains="nonexistent"))

    assert page.items == ()
    assert page.total == 0


# -- list_products: sorting ---------------------------------------------


def test_list_products_sorts_by_name_ascending_by_default() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(limit=100))

    names = [product.name for product in page.items]
    assert names == sorted(names)


def test_list_products_sorts_by_price_descending() -> None:
    repository = _repository()

    page = repository.list_products(
        ProductQuery(sort=SortKey.PRICE, direction=SortDirection.DESC, limit=100)
    )

    prices = [product.price_minor for product in page.items]
    assert prices == sorted(prices, reverse=True)
    assert page.items[0].id == "p-rust"


def test_list_products_unknown_sort_key_raises_domain_error() -> None:
    repository = _repository()
    query = ProductQuery(sort="release_date")  # type: ignore[arg-type]

    with pytest.raises(UnknownSortKeyError) as excinfo:
        repository.list_products(query)

    assert excinfo.value.sort_key == "release_date"


# -- list_products: pagination -------------------------------------------


def test_list_products_pagination_returns_requested_slice() -> None:
    repository = _repository()

    first_page = repository.list_products(ProductQuery(limit=2, offset=0))
    second_page = repository.list_products(ProductQuery(limit=2, offset=2))

    assert len(first_page.items) == 2
    assert len(second_page.items) == 2
    assert first_page.total == 4
    assert second_page.total == 4
    assert {p.id for p in first_page.items}.isdisjoint(
        {p.id for p in second_page.items}
    )


def test_list_products_pagination_offset_beyond_total_is_empty() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(limit=10, offset=100))

    assert page.items == ()
    assert page.total == 4


def test_list_products_limit_zero_returns_no_items_but_reports_total() -> None:
    repository = _repository()

    page = repository.list_products(ProductQuery(limit=0))

    assert page.items == ()
    assert page.total == 4


# -- get_product ------------------------------------------------------------


def test_get_product_returns_matching_product() -> None:
    repository = _repository()

    product = repository.get_product("p-python")

    assert product is not None
    assert product.name == "Python Fundamentals"


def test_get_product_returns_none_for_unknown_id() -> None:
    repository = _repository()

    assert repository.get_product("does-not-exist") is None


def test_get_product_detail_returns_none_when_not_seeded_as_detail() -> None:
    repository = _repository()

    assert repository.get_product_detail("p-python") is None


def test_get_product_detail_returns_reviews_and_long_description() -> None:
    review = Review(id="r-1", author="ana", rating=5, body="Loved it.")
    detail = ProductDetail(
        id="p-detail",
        name="Detailed Product",
        price_minor=2499,
        currency="USD",
        short_description="short",
        thumbnail_url="https://example.com/p-detail.png",
        category=EBOOKS,
        long_description="A much longer description of the product.",
        reviews=(review,),
    )
    repository = InMemoryRepository(products=[detail])

    fetched = repository.get_product_detail("p-detail")

    assert fetched is not None
    assert fetched.long_description == "A much longer description of the product."
    assert fetched.reviews == (review,)
    # A ProductDetail also satisfies plain get_product, per Liskov substitution.
    assert repository.get_product("p-detail") == detail


# -- Cart: get_cart -----------------------------------------------------


def test_get_cart_returns_empty_cart_for_unseen_session() -> None:
    repository = _repository()

    cart = repository.get_cart("session-1")

    assert cart == Cart(session_id="session-1", items=())
    assert cart.subtotal_minor == 0


# -- Cart: add_item -------------------------------------------------------


def test_add_item_creates_a_new_line_item() -> None:
    repository = _repository()

    cart = repository.add_item("session-1", "p-python", 2)

    assert len(cart.items) == 1
    assert cart.items[0].product.id == "p-python"
    assert cart.items[0].quantity == 2


def test_add_item_accumulates_quantity_for_an_existing_line_item() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 2)

    cart = repository.add_item("session-1", "p-python", 3)

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 5


def test_add_item_unknown_product_raises_domain_error() -> None:
    repository = _repository()

    with pytest.raises(UnknownProductError) as excinfo:
        repository.add_item("session-1", "does-not-exist", 1)

    assert excinfo.value.product_id == "does-not-exist"


def test_add_item_rejects_non_positive_quantity() -> None:
    repository = _repository()

    with pytest.raises(ValueError):
        repository.add_item("session-1", "p-python", 0)


# -- Cart: set_quantity ---------------------------------------------------


def test_set_quantity_updates_an_existing_line_item() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 1)

    cart = repository.set_quantity("session-1", "p-python", 7)

    assert cart.items[0].quantity == 7


def test_set_quantity_creates_a_new_line_item_when_absent() -> None:
    repository = _repository()

    cart = repository.set_quantity("session-1", "p-rust", 4)

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 4


def test_set_quantity_zero_removes_the_line_item() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 3)

    cart = repository.set_quantity("session-1", "p-python", 0)

    assert cart.items == ()


def test_set_quantity_unknown_product_raises_domain_error() -> None:
    repository = _repository()

    with pytest.raises(UnknownProductError):
        repository.set_quantity("session-1", "does-not-exist", 1)


def test_set_quantity_negative_raises_value_error() -> None:
    repository = _repository()

    with pytest.raises(ValueError):
        repository.set_quantity("session-1", "p-python", -1)


# -- Cart: remove_item ----------------------------------------------------


def test_remove_item_removes_an_existing_line_item() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 1)
    repository.add_item("session-1", "p-rust", 1)

    cart = repository.remove_item("session-1", "p-python")

    assert len(cart.items) == 1
    assert cart.items[0].product.id == "p-rust"


def test_remove_item_missing_product_is_a_noop() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 1)

    cart = repository.remove_item("session-1", "does-not-exist")

    assert len(cart.items) == 1


# -- Cart / LineItem quantity arithmetic in integer minor units -----------


def test_line_item_subtotal_minor_is_price_times_quantity() -> None:
    product = _product("p-python", "Python Fundamentals", 1999)

    item = LineItem(product=product, quantity=3)

    assert item.subtotal_minor == 5997


def test_line_item_rejects_non_positive_quantity() -> None:
    product = _product("p-python", "Python Fundamentals", 1999)

    with pytest.raises(ValueError):
        LineItem(product=product, quantity=0)


def test_cart_subtotal_minor_sums_all_line_items_exactly() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-python", 2)  # 2 * 1999 = 3998
    repository.add_item("session-1", "p-rust", 1)  # 1 * 2999 = 2999

    cart = repository.get_cart("session-1")

    assert cart.subtotal_minor == 6997


def test_cart_subtotal_minor_updates_after_quantity_change() -> None:
    repository = _repository()
    repository.add_item("session-1", "p-algebra", 4)  # 4 * 999 = 3996

    cart = repository.set_quantity("session-1", "p-algebra", 1)  # 1 * 999 = 999

    assert cart.subtotal_minor == 999


# -- Carts are isolated per session ---------------------------------------


def test_carts_are_isolated_per_session() -> None:
    repository = _repository()
    repository.add_item("session-a", "p-python", 1)

    cart_b = repository.get_cart("session-b")

    assert cart_b.items == ()


def test_get_product_detail_is_part_of_the_protocol() -> None:
    """BE-05's detail route must reach reviews without downcasting.

    Reachable only on the concrete fake, `ProductDetail` forced callers to
    either isinstance-check the result of `get_product` or annotate against
    the fake — both of which defeat the storage-agnostic boundary.
    """
    assert hasattr(ProductRepository, "get_product_detail")

    repo: ProductRepository = InMemoryRepository()
    assert isinstance(repo, ProductRepository)


def test_limit_above_the_maximum_page_size_is_rejected() -> None:
    """An unbounded limit becomes an unbounded scan once this reaches SQL."""
    with pytest.raises(ValueError, match="limit must be <="):
        ProductQuery(limit=MAX_PAGE_SIZE + 1)


def test_limit_at_the_maximum_page_size_is_allowed() -> None:
    assert ProductQuery(limit=MAX_PAGE_SIZE).limit == MAX_PAGE_SIZE
