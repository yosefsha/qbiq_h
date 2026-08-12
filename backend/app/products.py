"""Business logic behind the product catalogue HTTP surface (BE-05).

Kept separate from `app/api/products.py` so the route handlers stay thin per
`docs/coding-instructions.md`: this module builds the domain `ProductQuery`,
validates an inbound `category` filter, and converts domain types into the
wire-facing Pydantic schemas in `app/models.py`. It depends only on the
`ProductRepository` Protocol, never on a concrete storage implementation, so
it works unchanged against `SqlProductRepository` in production and
`InMemoryRepository` in tests.
"""

from __future__ import annotations

from app.domain.catalog import ProductQuery, SortDirection, SortKey
from app.domain.repositories import ProductRepository
from app.models import (
    CategoryResponse,
    ProductDetailResponse,
    ProductListResponse,
    ProductSummaryResponse,
)


class UnknownCategoryError(Exception):
    """Raised when a `category` filter names a slug no `Category` has.

    An HTTP input-validation concern, not a storage failure — nothing about
    the repository failed, the caller-supplied filter value just names
    nothing. Distinct from `app.domain.errors.UnknownSortKeyError`, which a
    repository implementation raises; this is raised by `ProductCatalog`
    itself, before any repository call that would use the filter. The route
    layer maps it to 422 per BE-05's Contract: "An unknown category slug
    returns 422, not an empty 200" — an empty result set and an invalid
    filter are different outcomes and must not look identical to the client.
    """

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Unknown category slug: {slug!r}")


class ProductCatalog:
    """Read access to the catalogue, shaped for the HTTP layer."""

    def __init__(self, repository: ProductRepository) -> None:
        self._repository = repository

    def list_products(
        self,
        *,
        name: str | None,
        category: str | None,
        sort: SortKey,
        direction: SortDirection,
        limit: int,
        offset: int,
    ) -> ProductListResponse:
        """Returns a page of the catalogue matching the given filters.

        Raises:
            UnknownCategoryError: if `category` is not `None` and matches no
                known `Category` slug.
            app.domain.errors.UnknownSortKeyError: never, in practice — `sort`
                is typed as `SortKey` at the HTTP boundary — but the route
                layer still maps it to 422 as a backstop.
        """
        if category is not None:
            self._require_known_category(category)

        query = ProductQuery(
            name_contains=name,
            category_slug=category,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        )
        page = self._repository.list_products(query)
        return ProductListResponse(
            items=tuple(
                ProductSummaryResponse.from_domain(product) for product in page.items
            ),
            total=page.total,
            limit=limit,
            offset=offset,
        )

    def get_product_detail(self, product_id: str) -> ProductDetailResponse | None:
        """Returns the detail page for `product_id`, or `None` if absent."""
        detail = self._repository.get_product_detail(product_id)
        if detail is None:
            return None
        return ProductDetailResponse.from_domain(detail)

    def list_categories(self) -> tuple[CategoryResponse, ...]:
        """Returns every known `Category`."""
        return tuple(
            CategoryResponse.from_domain(category)
            for category in self._repository.list_categories()
        )

    def _require_known_category(self, slug: str) -> None:
        known_slugs = {category.slug for category in self._repository.list_categories()}
        if slug not in known_slugs:
            raise UnknownCategoryError(slug)
