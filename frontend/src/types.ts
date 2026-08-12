/**
 * Shared domain types, matching the language defined in CONTEXT.md.
 *
 * Prices are always integer minor units (e.g. cents) paired with a currency
 * code — never a float or a formatted string. This keeps money arithmetic
 * exact and matches the backend's wire format.
 */

/** ISO 4217 currency code, e.g. "USD". */
export type CurrencyCode = string

/** A monetary amount transported as integer minor units plus a currency code. */
export interface Money {
  priceMinor: number
  currency: CurrencyCode
}

/** The kind of digital good a Product is. Every Product has exactly one. */
export interface Category {
  id: string
  name: string
}

/** A shopper's written verdict on a Product. */
export interface Review {
  id: string
  productId: string
  author: string
  rating: number
  body: string
  createdAt: string
}

/** A digital good offered for sale — an e-book, a software licence, or an online course. */
export interface Product {
  id: string
  name: string
  shortDescription: string
  thumbnailUrl: string
  price: Money
  category: Category
}

/** Product detail, extending the catalogue listing shape with long-form content. */
export interface ProductDetail extends Product {
  longDescription: string
  reviews: Review[]
}

/** One Product within a Cart, together with the quantity wanted of it. */
export interface LineItem {
  product: Product
  quantity: number
}

/** The set of Products a Shopper intends to buy, held on the server and read by the browser. */
export interface Cart {
  id: string
  lineItems: LineItem[]
  total: Money
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
