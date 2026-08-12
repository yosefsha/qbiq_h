"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class HealthResponse(BaseModel):
    """Response body for `GET /health`."""

    status: str


class _CamelModel(BaseModel):
    """Base for every wire-facing schema: `snake_case` in Python, camelCase on
    the wire (`priceMinor`, `shortDescription`, `thumbnailUrl`, `productId`).

    `alias_generator=to_camel` produces what a client actually sends and
    receives; `populate_by_name=True` lets Python on this side still
    construct instances by their snake_case field name (`price_minor=...`
    in `from_domain`, `CartView(total_minor=...)`), which is what every
    other dataclass and model in this codebase looks like. FastAPI's
    default `response_model_by_alias` serialises the alias on the way out.

    Shared by the catalogue schemas (BE-05) and the Cart schemas (BE-07),
    which arrived at this same base independently — one definition, so the
    two halves of the API cannot drift on casing.

    `from_attributes=True` is what lets `from_domain` below read a domain
    dataclass directly, so no subclass has to restate its fields.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )

    @classmethod
    def from_domain(cls, obj: object) -> Self:
        """Builds this wire model from the domain dataclass it mirrors.

        Derived, not written out. Every schema here shares its field names
        with the frozen dataclass in `app.domain.catalog`, so Pydantic can
        read the attributes itself — recursively, since the nested schemas
        share this base. Each subclass previously carried a `from_domain`
        listing all of its fields, and `ProductDetailResponse` listed all
        of its parent's too; adding a field to a domain type then meant
        editing every one of them, and forgetting simply dropped the field
        from the response with no test failing.

        Extra attributes are ignored, so a `ProductDetail` passed where a
        `ProductSummaryResponse` is wanted is projected down rather than
        rejected — which is what `GET /api/products` relies on when the
        repository hands it a detail (Liskov).
        """
        return cls.model_validate(obj)


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


class ReviewResponse(_CamelModel):
    """Wire shape for `Review`."""

    id: str
    author: str
    rating: int
    body: str


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


class ProductDetailResponse(ProductSummaryResponse):
    """Wire shape for a product detail page: a summary plus long-form content."""

    long_description: str
    reviews: tuple[ReviewResponse, ...]


class ProductListResponse(_CamelModel):
    """Response body for `GET /api/products`: a page plus its paging state."""

    items: tuple[ProductSummaryResponse, ...]
    total: int
    limit: int
    offset: int


class _CamelRequestModel(_CamelModel):
    """Base for Cart request bodies.

    `extra="forbid"` on top of `_CamelModel`: this API never accepts a
    price from the client (every total is computed server-side from the
    catalogue — see `app.api.cart`), so an extra `unitPriceMinor` or
    `price` field in a request body is a 422 validation error, not a value
    silently accepted and ignored.
    """

    # Merged over `_CamelModel`'s config, so only the difference is stated.
    model_config = ConfigDict(extra="forbid")


class CartLineItemView(_CamelModel):
    """One line of a rendered Cart.

    `unit_price_minor` and `subtotal_minor` are always re-read from the
    catalogue at response time (see `app.api.cart._to_cart_view`) — never
    the client's own numbers and never a value persisted in Redis — so a
    catalogue price change is reflected immediately and a stale price can
    never be served.
    """

    product_id: str
    name: str
    unit_price_minor: int
    quantity: int
    subtotal_minor: int


class CartView(_CamelModel):
    """Response body shared by every Cart endpoint.

    `total_minor` is the integer sum of every line's `subtotal_minor` —
    plain integer addition, never a float and never rounded. See
    `app.api.cart._to_cart_view` for what `currency` reports on an empty
    Cart.
    """

    items: list[CartLineItemView]
    total_minor: int
    currency: str


class AddCartItemRequest(_CamelRequestModel):
    """Body of `POST /api/cart/items`."""

    product_id: str
    quantity: int = Field(ge=1)


class SetCartItemQuantityRequest(_CamelRequestModel):
    """Body of `PATCH /api/cart/items/{productId}`.

    `quantity` is `ge=1`, not `ge=0` like the domain `CartRepository.
    set_quantity`, which permits `0` to remove a line item. This route
    deliberately enforces the stricter floor: removal is
    `DELETE /api/cart/items/{productId}`, so a `PATCH` to `0` is a 422
    rather than a second spelling of delete a client could come to rely on.
    """

    quantity: int = Field(ge=1)
