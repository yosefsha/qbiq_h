"""Product catalogue routes (BE-05).

Thin FastAPI wiring only: FastAPI's `Query(..., ge=..., le=...)` and the
`SortKey`/`SortDirection` enum types enforce paging bounds and valid
sort/direction values before a handler ever runs, so those show up as 422
with no business logic involved. Everything else — building the domain
query, validating the `category` filter, and shaping the response — is
delegated to `app.products.ProductCatalog`.

No SQLAlchemy import may appear in this module (an explicit Done-when on
BE-05): every handler depends on the `ProductRepository` Protocol via
`get_product_repository`, a dependency `app.main` overrides with a
request-scoped `SqlProductRepository` (`app.api.deps.get_sql_product_repository`)
and tests override with `app.domain.fakes.InMemoryRepository` — either way,
this module never knows which one it got.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.providers import get_product_repository
from app.domain.catalog import MAX_PAGE_SIZE, SortDirection, SortKey
from app.domain.errors import UnknownSortKeyError
from app.domain.repositories import ProductRepository
from app.models import CategoryResponse, ProductDetailResponse, ProductListResponse
from app.products import ProductCatalog, UnknownCategoryError

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products", response_model=ProductListResponse)
def list_products(
    name: str | None = Query(
        default=None, description="Case-insensitive substring match on product name."
    ),
    category: str | None = Query(
        default=None, description="Category slug to filter by."
    ),
    sort: SortKey = Query(default=SortKey.NAME),
    direction: SortDirection = Query(default=SortDirection.ASC),
    limit: int = Query(default=20, ge=0, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    repository: ProductRepository = Depends(get_product_repository),
) -> ProductListResponse:
    """Lists the catalogue, filtered, sorted, and paged.

    An unknown `category` slug is a 422, not an empty page — see
    `ProductCatalog._require_known_category`. `limit` above `MAX_PAGE_SIZE`
    is rejected by the `Query(..., le=MAX_PAGE_SIZE)` bound above before this
    body runs at all, so it never reaches `ProductQuery.__post_init__`.
    """
    catalog = ProductCatalog(repository)
    try:
        return catalog.list_products(
            name=name,
            category=category,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    except UnknownCategoryError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown category: {exc.slug!r}"
        ) from exc
    except UnknownSortKeyError as exc:
        # Unreachable via HTTP in practice: `sort` above is typed as `SortKey`,
        # so FastAPI rejects any other value itself. Mapped anyway as a
        # backstop rather than letting it fall through to an unhandled 500.
        raise HTTPException(
            status_code=422, detail=f"Unknown sort key: {exc.sort_key!r}"
        ) from exc
    except ValueError as exc:
        # Backstop for `ProductQuery.__post_init__`'s own limit/offset
        # invariants. The `Query` bounds above already enforce them before
        # construction, so this should be unreachable too.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/products/{product_id}", response_model=ProductDetailResponse)
def get_product(
    product_id: str,
    repository: ProductRepository = Depends(get_product_repository),
) -> ProductDetailResponse:
    """Returns the detail page for `product_id`.

    `product_id` is untyped (`str`) rather than `int`: a non-numeric id such
    as `/api/products/abc` must 404, matching
    `ProductRepository.get_product_detail`'s own contract of returning
    `None` for it, rather than FastAPI rejecting it as a 422 path-parameter
    type error before the repository is even asked.
    """
    catalog = ProductCatalog(repository)
    detail = catalog.get_product_detail(product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id!r} not found")
    return detail


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(
    repository: ProductRepository = Depends(get_product_repository),
) -> list[CategoryResponse]:
    """Lists every category, for the catalogue's filter UI."""
    catalog = ProductCatalog(repository)
    return list(catalog.list_categories())
