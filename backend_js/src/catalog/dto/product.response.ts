/**
 * Wire shapes for the catalogue, and the projections that build them.
 *
 * Every field name here is the camelCase one a client actually sees, and it is
 * identical to the domain field name — TypeScript needs no alias layer where
 * the Python service needs `alias_generator=to_camel`.
 *
 * The projections are explicit rather than a spread of the domain object. A
 * `ProductDetail` is a `Product`, so `listProducts` may legitimately be handed
 * one; spreading it would leak `longDescription` and `reviews` into a listing
 * row. Naming the summary's fields is what keeps the two responses distinct.
 */

import { Category, Product, ProductDetail, ProductPage, Review } from '../../domain/catalog'

export interface CategoryResponse {
  slug: string
  name: string
}

export interface ReviewResponse {
  id: string
  author: string
  rating: number
  body: string
}

export interface ProductSummaryResponse {
  id: string
  name: string
  priceMinor: number
  currency: string
  shortDescription: string
  thumbnailUrl: string
  category: CategoryResponse
}

export interface ProductDetailResponse extends ProductSummaryResponse {
  longDescription: string
  reviews: ReviewResponse[]
}

export interface ProductListResponse {
  items: ProductSummaryResponse[]
  total: number
  limit: number
  offset: number
}

export function toCategoryResponse(category: Category): CategoryResponse {
  return { slug: category.slug, name: category.name }
}

function toReviewResponse(review: Review): ReviewResponse {
  return { id: review.id, author: review.author, rating: review.rating, body: review.body }
}

/**
 * `category` is always present, never omitted or `null`, so the SPA can render
 * a category chip on a listing page without a second request for the product's
 * detail.
 */
export function toProductSummaryResponse(product: Product): ProductSummaryResponse {
  return {
    id: product.id,
    name: product.name,
    priceMinor: product.priceMinor,
    currency: product.currency,
    shortDescription: product.shortDescription,
    thumbnailUrl: product.thumbnailUrl,
    category: toCategoryResponse(product.category),
  }
}

export function toProductDetailResponse(detail: ProductDetail): ProductDetailResponse {
  return {
    ...toProductSummaryResponse(detail),
    longDescription: detail.longDescription,
    reviews: detail.reviews.map(toReviewResponse),
  }
}

export function toProductListResponse(
  page: ProductPage,
  limit: number,
  offset: number,
): ProductListResponse {
  return {
    items: page.items.map(toProductSummaryResponse),
    total: page.total,
    limit,
    offset,
  }
}
