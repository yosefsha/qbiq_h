"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.domain.catalog import Category, Product, ProductDetail, Review


class HealthResponse(BaseModel):
    """Response body for `GET /health`."""

    status: str


class _CamelModel(BaseModel):
    """Base for wire-facing schemas: `snake_case` in Python, camelCase on
    the wire (see BE-05's Contract: `priceMinor`, `shortDescription`,
    `thumbnailUrl`, `longDescription`).

    `populate_by_name=True` so a model can still be constructed with its
    Python field name (`price_minor=...`) from `from_domain`, while
    `response_model_by_alias` (FastAPI's default) serialises the alias —
    `to_camel` — on the way out.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CategoryResponse(_CamelModel):
    """Wire shape for `Category`: `{slug, name}`.

    The issue's Contract wrote this as `{slug, label}`, but the domain field
    settled on `Category.name` (`app/domain/catalog.py`) — the DB column
    `category.label` is mapped to it at the storage boundary in
    `SqlProductRepository._to_category`, and that mapping stays there. `name`
    is used here instead, for consistency with the domain and with the
    `category` object nested in `ProductSummaryResponse` below — see the
    BE-05 PR description for the full rationale.
    """

    slug: str
    name: str

    @classmethod
    def from_domain(cls, category: Category) -> "CategoryResponse":
        return cls(slug=category.slug, name=category.name)


class ReviewResponse(_CamelModel):
    """Wire shape for `Review`."""

    id: str
    author: str
    rating: int
    body: str

    @classmethod
    def from_domain(cls, review: Review) -> "ReviewResponse":
        return cls(
            id=review.id, author=review.author, rating=review.rating, body=review.body
        )


class ProductSummaryResponse(_CamelModel):
    """Wire shape for a catalogue listing row.

    `category` is always present, never omitted or `null`, so the SPA can
    render a category chip on a listing page without a second request for
    the product's detail.
    """

    id: str
    name: str
    price_minor: int
    currency: str
    short_description: str
    thumbnail_url: str
    category: CategoryResponse

    @classmethod
    def from_domain(cls, product: Product) -> "ProductSummaryResponse":
        return cls(
            id=product.id,
            name=product.name,
            price_minor=product.price_minor,
            currency=product.currency,
            short_description=product.short_description,
            thumbnail_url=product.thumbnail_url,
            category=CategoryResponse.from_domain(product.category),
        )


class ProductDetailResponse(ProductSummaryResponse):
    """Wire shape for a product detail page: a summary plus long-form content."""

    long_description: str
    reviews: tuple[ReviewResponse, ...]

    @classmethod
    def from_domain(cls, product: ProductDetail) -> "ProductDetailResponse":
        return cls(
            id=product.id,
            name=product.name,
            price_minor=product.price_minor,
            currency=product.currency,
            short_description=product.short_description,
            thumbnail_url=product.thumbnail_url,
            category=CategoryResponse.from_domain(product.category),
            long_description=product.long_description,
            reviews=tuple(ReviewResponse.from_domain(r) for r in product.reviews),
        )


class ProductListResponse(_CamelModel):
    """Response body for `GET /api/products`: a page plus its paging state."""

    items: tuple[ProductSummaryResponse, ...]
    total: int
    limit: int
    offset: int
