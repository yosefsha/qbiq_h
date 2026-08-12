/**
 * Shared domain types, matching the language defined in CONTEXT.md.
 *
 * These mirror the backend's wire format exactly, field for field. They were
 * originally written from the plan, before BE-05 and BE-07 existed, and had
 * drifted: prices were nested under a `Money` object, `Category` was keyed by
 * `id` rather than `slug`, `Review` carried a `productId` and `createdAt` the
 * API never sends, and `Cart` used `lineItems`/`total` where the API sends
 * `items`/`totalMinor`. Each shape below is now taken from an actual response.
 *
 * Prices are always integer minor units (e.g. cents) paired with a currency
 * code — never a float and never a formatted string. Formatting happens once,
 * at render time, via `Intl.NumberFormat`. The API deliberately sends them
 * flat (`priceMinor` + `currency`) rather than nested, so these do too:
 * a wrapper type here would have to be built and unwrapped on every response,
 * which is exactly the sort of translation layer that lets drift back in.
 */

/** ISO 4217 currency code, e.g. "USD". */
export type CurrencyCode = string

/**
 * The kind of digital good a Product is. Every Product has exactly one.
 *
 * Identified by `slug`, which is what `GET /api/products?category=` accepts —
 * there is no separate opaque id on the wire.
 */
export interface Category {
  slug: string
  name: string
}

/** A shopper's written verdict on a Product. */
export interface Review {
  id: string
  author: string
  rating: number
  body: string
}

/** A digital good offered for sale — an e-book, a software licence, or an online course. */
export interface Product {
  id: string
  name: string
  priceMinor: number
  currency: CurrencyCode
  shortDescription: string
  thumbnailUrl: string
  category: Category
}

/** Product detail, extending the catalogue listing shape with long-form content. */
export interface ProductDetail extends Product {
  longDescription: string
  reviews: Review[]
}

/** Response body of `GET /api/products`: one page plus its paging state. */
export interface ProductPage {
  items: Product[]
  total: number
  limit: number
  offset: number
}

/**
 * One line of a rendered Cart.
 *
 * Flat, not a nested `Product`: the server re-reads the price from the
 * catalogue on every Cart response, so a line carries the price as of *now*
 * rather than a snapshot taken when it was added.
 */
export interface CartLineItem {
  productId: string
  name: string
  unitPriceMinor: number
  quantity: number
  subtotalMinor: number
}

/**
 * The set of Products a Shopper intends to buy — held on the server (ADR-001)
 * and only mirrored here.
 *
 * `totalMinor` is the server's own integer sum. Never recompute it in the
 * browser: the displayed total must be the total the server returned, or the
 * two can disagree.
 */
export interface Cart {
  items: CartLineItem[]
  totalMinor: number
  currency: CurrencyCode
}

/**
 * API client result types. Every API call resolves to one of these instead
 * of a raw `Response`, so views branch on `ok` rather than inspecting HTTP
 * plumbing directly.
 */

/** The request reached the server, which rejected it with a non-2xx status. */
export interface ApiHttpError {
  kind: 'http'
  status: number
  message: string
}

/** The request never reached the server — offline, DNS failure, CORS, etc. */
export interface ApiNetworkError {
  kind: 'network'
  message: string
}

/** The server responded with a 2xx status but the body wasn't valid JSON. */
export interface ApiParseError {
  kind: 'parse'
  message: string
}

export type ApiError = ApiHttpError | ApiNetworkError | ApiParseError

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

/**
 * Lifecycle of a single `apiClient` call driven by `useAsyncRequest`.
 * `idle` only occurs when a request has not been issued yet (see the
 * `immediate: false` option).
 */
export type AsyncRequestStatus = 'idle' | 'loading' | 'success' | 'error'

/**
 * The human-facing rendering of an `ApiError`: what to tell the shopper, and
 * whether offering a retry affordance could plausibly help. A 404 means the
 * resource doesn't exist — re-issuing the same request will just fail again,
 * so `retryable` is false. A network failure or a 5xx is often transient, so
 * `retryable` is true.
 */
export interface ErrorPresentation {
  kind: ApiError['kind']
  title: string
  message: string
  retryable: boolean
}
