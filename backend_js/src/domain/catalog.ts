/**
 * Catalogue domain types: categories, products, reviews, and queries.
 *
 * Plain readonly interfaces plus factory functions — the TypeScript
 * equivalent of the frozen dataclasses in `backend/app/domain/catalog.py`.
 * Prices are always integer minor units plus an ISO 4217 currency code (see
 * `docs/adr/ADR-003-managed-aws-data-tier.md`), never a float, so totals
 * computed downstream stay exact integer arithmetic.
 */

/** Fields a product listing can be ordered by. */
export enum SortKey {
  NAME = 'name',
  PRICE = 'price',
}

/** Direction of a product listing sort. */
export enum SortDirection {
  ASC = 'asc',
  DESC = 'desc',
}

/** The kind of digital good a Product is. Every Product has exactly one. */
export interface Category {
  readonly slug: string
  readonly name: string
}

/** A shopper's written verdict on a Product. */
export interface Review {
  readonly id: string
  readonly author: string
  readonly rating: number
  readonly body: string
}

/**
 * Builds a `Review`, enforcing the rating range the domain promises.
 *
 * The check lives in a factory rather than a constructor because these types
 * are structural interfaces; every place that materialises a Review from
 * storage goes through here, which is what makes the invariant real.
 */
export function makeReview(review: Review): Review {
  if (!(review.rating >= 1 && review.rating <= 5)) {
    throw new RangeError('rating must be between 1 and 5')
  }
  return review
}

/** A digital good offered for sale — an e-book, a licence, or a course. */
export interface Product {
  readonly id: string
  readonly name: string
  readonly priceMinor: number
  readonly currency: string
  readonly shortDescription: string
  readonly thumbnailUrl: string
  readonly category: Category
}

/** A `Product` plus the extra content shown on its detail page. */
export interface ProductDetail extends Product {
  readonly longDescription: string
  readonly reviews: readonly Review[]
}

/**
 * Narrows a `Product` to a `ProductDetail`.
 *
 * Structural types carry no runtime tag, so this stands in for Python's
 * `isinstance(product, ProductDetail)` — used by the cache to record what a
 * payload actually is rather than what the calling method asked for.
 */
export function isProductDetail(product: Product): product is ProductDetail {
  return (
    typeof (product as ProductDetail).longDescription === 'string' &&
    Array.isArray((product as ProductDetail).reviews)
  )
}

/**
 * Largest page a caller may request. The HTTP layer surfaces a request above
 * this as a 422 rather than silently clamping, so a client paging with a
 * too-large limit learns it is doing so instead of quietly getting short
 * pages.
 */
export const MAX_PAGE_SIZE = 100

/** Filter, sort, and page parameters for listing the catalogue. */
export interface ProductQuery {
  readonly nameContains: string | null
  readonly categorySlug: string | null
  readonly sort: SortKey
  readonly direction: SortDirection
  readonly limit: number
  readonly offset: number
}

/**
 * Builds a `ProductQuery`, applying the defaults and the paging invariants.
 *
 * The ceiling is enforced here so every repository implementation inherits
 * it. The catalogue is public and unauthenticated (ADR-002), so without a
 * bound `?limit=1000000000` becomes an unbounded scan of the products table
 * the moment the query reaches Postgres — cheap for the caller, expensive
 * for the database.
 */
export function makeProductQuery(query: Partial<ProductQuery> = {}): ProductQuery {
  const resolved: ProductQuery = {
    nameContains: query.nameContains ?? null,
    categorySlug: query.categorySlug ?? null,
    sort: query.sort ?? SortKey.NAME,
    direction: query.direction ?? SortDirection.ASC,
    limit: query.limit ?? 20,
    offset: query.offset ?? 0,
  }
  if (resolved.limit < 0) {
    throw new RangeError('limit must be >= 0')
  }
  if (resolved.limit > MAX_PAGE_SIZE) {
    throw new RangeError(`limit must be <= ${MAX_PAGE_SIZE}`)
  }
  if (resolved.offset < 0) {
    throw new RangeError('offset must be >= 0')
  }
  return resolved
}

/** A page of `Product`s together with the total count matching the query. */
export interface ProductPage {
  readonly items: readonly Product[]
  readonly total: number
}
