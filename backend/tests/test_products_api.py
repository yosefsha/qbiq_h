"""Tests for the product catalogue routes (BE-05).

Uses `TestClient` against `app.main.app` with `app.domain.fakes.InMemoryRepository`
injected via `app.dependency_overrides` — no database needed. Integration
tests for `SqlProductRepository` itself live in `test_product_repository.py`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.products import get_product_repository
from app.domain.catalog import (
    MAX_PAGE_SIZE,
    Category,
    Product,
    ProductDetail,
    Review,
)
from app.domain.fakes import InMemoryRepository
from app.main import app

EBOOKS = Category(slug="ebooks", name="E-Books")
COURSES = Category(slug="courses", name="Courses")


def _product(
    product_id: str, name: str, price_minor: int, category: Category = EBOOKS
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


def _product_detail(
    product_id: str,
    name: str,
    price_minor: int,
    category: Category = EBOOKS,
) -> ProductDetail:
    return ProductDetail(
        id=product_id,
        name=name,
        price_minor=price_minor,
        currency="USD",
        short_description=f"{name} short description",
        thumbnail_url=f"https://example.com/{product_id}.png",
        category=category,
        long_description=f"{name} long description",
        reviews=(
            Review(id="r-1", author="Ana", rating=5, body="Loved it."),
            Review(id="r-2", author="Ben", rating=3, body="It was fine."),
        ),
    )


@pytest.fixture(name="repository")
def repository_fixture() -> InMemoryRepository:
    return InMemoryRepository(
        products=[
            _product("1", "Python Fundamentals", 1999, EBOOKS),
            _product("2", "Rust in Practice", 2999, EBOOKS),
            _product_detail("3", "Algebra Refresher", 999, COURSES),
        ]
    )


@pytest.fixture(name="client")
def client_fixture(repository: InMemoryRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_product_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_product_repository]


# -- GET /api/products: happy path --------------------------------------


def test_list_products_returns_items_with_camel_case_keys(
    client: TestClient,
) -> None:
    response = client.get("/api/products")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 3

    item = next(i for i in body["items"] if i["id"] == "1")
    # camelCase keys must actually be present in the serialized JSON, not
    # just the OpenAPI schema.
    assert item["priceMinor"] == 1999
    assert item["shortDescription"] == "Python Fundamentals short description"
    assert item["thumbnailUrl"] == "https://example.com/1.png"
    assert "price_minor" not in item
    assert "short_description" not in item
    assert "thumbnail_url" not in item


def test_list_products_category_is_present_on_every_item(client: TestClient) -> None:
    response = client.get("/api/products")

    body = response.json()
    for item in body["items"]:
        assert item["category"]["slug"]
        assert item["category"]["name"]


def test_list_products_filters_by_name(client: TestClient) -> None:
    response = client.get("/api/products", params={"name": "python"})

    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Python Fundamentals"]
    assert body["total"] == 1


def test_list_products_sorts_by_price_descending(client: TestClient) -> None:
    response = client.get(
        "/api/products", params={"sort": "price", "direction": "desc"}
    )

    body = response.json()
    prices = [item["priceMinor"] for item in body["items"]]
    assert prices == sorted(prices, reverse=True)


def test_list_products_paginates(client: TestClient) -> None:
    response = client.get("/api/products", params={"limit": 1, "offset": 1})

    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1


# -- category filter: 422 vs empty 200 -----------------------------------


def test_list_products_with_unknown_category_slug_returns_422(
    client: TestClient,
) -> None:
    response = client.get("/api/products", params={"category": "does-not-exist"})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_unknown_category_422_is_distinguishable_from_a_valid_empty_result(
    client: TestClient,
) -> None:
    """An unknown slug and a valid filter matching nothing must not look
    the same to the client."""
    unknown_response = client.get("/api/products", params={"category": "nope"})
    empty_but_valid_response = client.get(
        "/api/products", params={"category": "ebooks", "name": "no-such-product"}
    )

    assert unknown_response.status_code == 422
    assert empty_but_valid_response.status_code == 200
    empty_body = empty_but_valid_response.json()
    assert empty_body["items"] == []
    assert empty_body["total"] == 0


def test_list_products_with_known_category_slug_returns_200(
    client: TestClient,
) -> None:
    response = client.get("/api/products", params={"category": "courses"})

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Algebra Refresher"]


# -- limit/offset validation ----------------------------------------------


def test_list_products_limit_above_max_page_size_returns_422_not_a_clamp(
    client: TestClient,
) -> None:
    response = client.get("/api/products", params={"limit": MAX_PAGE_SIZE + 1})

    assert response.status_code == 422
    # Not clamped: a 200 with a bounded page would hide that the request was
    # rejected, which is exactly the outcome MAX_PAGE_SIZE forbids.
    assert response.status_code != 200


def test_list_products_limit_at_max_page_size_is_accepted(
    client: TestClient,
) -> None:
    response = client.get("/api/products", params={"limit": MAX_PAGE_SIZE})

    assert response.status_code == 200


def test_list_products_negative_offset_returns_422(client: TestClient) -> None:
    response = client.get("/api/products", params={"offset": -1})

    assert response.status_code == 422


def test_list_products_negative_limit_returns_422(client: TestClient) -> None:
    response = client.get("/api/products", params={"limit": -1})

    assert response.status_code == 422


# -- sort/direction validation ---------------------------------------------


def test_list_products_invalid_sort_returns_422(client: TestClient) -> None:
    response = client.get("/api/products", params={"sort": "not-a-real-sort"})

    assert response.status_code == 422


def test_list_products_invalid_direction_returns_422(client: TestClient) -> None:
    response = client.get("/api/products", params={"direction": "sideways"})

    assert response.status_code == 422


# -- GET /api/products/{id} -------------------------------------------------


def test_get_product_returns_detail_with_camel_case_keys(client: TestClient) -> None:
    response = client.get("/api/products/3")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "3"
    assert body["longDescription"] == "Algebra Refresher long description"
    assert "long_description" not in body
    assert {review["author"] for review in body["reviews"]} == {"Ana", "Ben"}
    assert body["category"] == {"slug": "courses", "name": "Courses"}


def test_get_product_unknown_numeric_id_returns_404_with_json_body(
    client: TestClient,
) -> None:
    response = client.get("/api/products/999999")

    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)


def test_get_product_non_numeric_id_returns_404_not_500_or_422(
    client: TestClient,
) -> None:
    response = client.get("/api/products/abc")

    assert response.status_code == 404
    assert "detail" in response.json()


# -- GET /api/categories -----------------------------------------------------


def test_list_categories_returns_slug_and_name(client: TestClient) -> None:
    response = client.get("/api/categories")

    assert response.status_code == 200
    body = response.json()
    assert {"slug": "courses", "name": "Courses"} in body
    assert {"slug": "ebooks", "name": "E-Books"} in body
    for category in body:
        assert set(category) == {"slug", "name"}


def test_list_categories_matches_the_category_shape_nested_in_products(
    client: TestClient,
) -> None:
    """`{slug, name}` must be identical between the categories endpoint and
    the `category` object nested in a `ProductSummary` — the JSON field
    naming decision is applied consistently everywhere."""
    categories_response = client.get("/api/categories").json()
    products_response = client.get("/api/products").json()

    nested_category = products_response["items"][0]["category"]
    assert set(nested_category) == {"slug", "name"}
    matching = next(
        c for c in categories_response if c["slug"] == nested_category["slug"]
    )
    assert matching == nested_category


# -- OpenAPI schema -----------------------------------------------------


def test_openapi_schema_reflects_real_response_shapes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/products" in schema["paths"]
    assert "/api/products/{product_id}" in schema["paths"]
    assert "/api/categories" in schema["paths"]

    components = schema["components"]["schemas"]
    product_list_schema = components["ProductListResponse"]
    assert set(product_list_schema["properties"]) == {
        "items",
        "total",
        "limit",
        "offset",
    }

    product_summary_schema = components["ProductSummaryResponse"]
    assert "priceMinor" in product_summary_schema["properties"]
    assert "shortDescription" in product_summary_schema["properties"]
    assert "thumbnailUrl" in product_summary_schema["properties"]
    assert "category" in product_summary_schema["properties"]

    product_detail_schema = components["ProductDetailResponse"]
    assert "longDescription" in product_detail_schema["properties"]
    assert "reviews" in product_detail_schema["properties"]

    category_schema = components["CategoryResponse"]
    assert set(category_schema["properties"]) == {"slug", "name"}


# -- No SQLAlchemy import in the routes module -------------------------


def test_routes_module_imports_no_sqlalchemy() -> None:
    """`app/api/products.py` must depend only on the `ProductRepository`
    Protocol, never on SQLAlchemy directly — an explicit Done-when on BE-05.

    Checked two ways: no `import`/`from` statement in the module's own
    source names `sqlalchemy` (prose mentioning the word, e.g. in a
    docstring, does not count), and — more strongly — `sqlalchemy` never
    appears among the module objects `app.api.products` actually bound into
    its namespace.
    """
    import ast
    import inspect

    import app.api.products as products_module

    source = inspect.getsource(products_module)
    tree = ast.parse(source)
    imported_root_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "sqlalchemy" not in imported_root_modules

    for name, value in vars(products_module).items():
        module_name = getattr(value, "__module__", "") or ""
        assert not module_name.startswith("sqlalchemy"), (
            f"{name} in app.api.products originates from sqlalchemy ({module_name})"
        )
