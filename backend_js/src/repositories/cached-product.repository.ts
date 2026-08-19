/**
 * Redis-backed caching decorator over a `ProductRepository`.
 *
 * Implements the same interface and delegates every read to an inner one, so
 * caching is invisible to the HTTP layer and is removed by handing the module
 * the inner repository directly.
 *
 * Keys
 *   `products:q:{stableHash(ProductQuery)}` for listings, and
 *   `products:id:{productId}` for single products. The id key is shared by
 *   `getProduct` and `getProductDetail` — a `ProductDetail` is a strict
 *   superset of a `Product` — so the payload carries a `kind` discriminator. A
 *   detail entry satisfies both methods (projected down for the summary); a
 *   summary entry satisfies only `getProduct`, and a detail read treats it as
 *   a miss and overwrites it with the richer payload. Without the
 *   discriminator a summary hit would silently answer a detail read with no
 *   `longDescription` and no reviews.
 *
 * Invalidation
 *   None. Nothing writes to the catalogue through this application — it
 *   changes only via the seeder or a direct database edit — so entries expire
 *   by TTL alone. The consequence is real and accepted: a reseed is invisible
 *   to the API for up to `CACHE_TTL_SECONDS`.
 *
 * Absent results are not cached. Distinguishing "cached absent" from "cache
 * miss" needs a sentinel, and buys nothing: a lookup by unknown id is already
 * a single indexed `SELECT` returning no rows.
 *
 * Every cache read and write is wrapped, so a Redis outage degrades to a miss
 * or a skipped write rather than a 500. `UnknownSortKeyError` is deliberately
 * thrown outside any of that, so it propagates and is never cached — an
 * invalid sort key must fail every time, not just once.
 */

import { Inject, Injectable } from '@nestjs/common'
import { createHash } from 'node:crypto'
import type { Redis } from 'ioredis'

import { JsonLogger } from '../common/logging/json-logger'
import {
  Category,
  Product,
  ProductDetail,
  ProductPage,
  ProductQuery,
  isProductDetail,
  makeReview,
} from '../domain/catalog'
import { ProductRepository } from '../domain/repositories'
import { REDIS_CLIENT } from '../redis/redis.constants'
import { settings } from '../config/settings'

const logger = new JsonLogger('app.cache')

const LIST_KEY_PREFIX = 'products:q:'
const PRODUCT_KEY_PREFIX = 'products:id:'

const KIND_PRODUCT = 'product'
const KIND_PRODUCT_DETAIL = 'product_detail'

type CachedPayload = Record<string, unknown>

/**
 * Hashes a query's field *values* in a fixed order.
 *
 * Not a hash of the object (property order is not a contract worth depending
 * on) and not its `JSON.stringify` in declaration order. Enum members
 * serialize by their string value, so the key stays stable across process
 * restarts and two queries with identical values share a key regardless of how
 * they were constructed.
 */
export function stableHash(query: ProductQuery): string {
  const values = [
    query.nameContains,
    query.categorySlug,
    query.sort,
    query.direction,
    query.limit,
    query.offset,
  ]
  return createHash('sha256').update(JSON.stringify(values), 'utf8').digest('hex')
}

function listKey(query: ProductQuery): string {
  return `${LIST_KEY_PREFIX}${stableHash(query)}`
}

function productKey(productId: string): string {
  return `${PRODUCT_KEY_PREFIX}${productId}`
}

/**
 * Serializes a product, tagging it by what it actually is.
 *
 * The kind is taken from the runtime shape rather than the calling method:
 * `getProduct` is free to return a `ProductDetail`, and when it does, storing
 * it as a detail is strictly better than truncating it.
 */
function encodeProduct(product: Product): string {
  return JSON.stringify({
    ...product,
    kind: isProductDetail(product) ? KIND_PRODUCT_DETAIL : KIND_PRODUCT,
  })
}

function toCategory(data: CachedPayload): Category {
  return { slug: String(data.slug), name: String(data.name) }
}

/** Rebuilds the summary shape, ignoring any detail-only fields present. */
function toProduct(data: CachedPayload): Product {
  return {
    id: String(data.id),
    name: String(data.name),
    priceMinor: Number(data.priceMinor),
    currency: String(data.currency),
    shortDescription: String(data.shortDescription),
    thumbnailUrl: String(data.thumbnailUrl),
    category: toCategory(data.category as CachedPayload),
  }
}

function toProductDetail(data: CachedPayload): ProductDetail {
  return {
    ...toProduct(data),
    longDescription: String(data.longDescription),
    reviews: (data.reviews as CachedPayload[]).map((review) =>
      makeReview({
        id: String(review.id),
        author: String(review.author),
        rating: Number(review.rating),
        body: String(review.body),
      }),
    ),
  }
}

/** A hit of either kind answers a summary read. */
function decodeProduct(data: CachedPayload): Product | null {
  if (data.kind !== KIND_PRODUCT && data.kind !== KIND_PRODUCT_DETAIL) {
    return null
  }
  return toProduct(data)
}

/** Only a detail hit answers a detail read; a summary hit is a miss. */
function decodeProductDetail(data: CachedPayload): ProductDetail | null {
  if (data.kind !== KIND_PRODUCT_DETAIL) {
    return null
  }
  return toProductDetail(data)
}

function encodePage(page: ProductPage): string {
  return JSON.stringify({ items: page.items, total: page.total })
}

function decodePage(data: CachedPayload): ProductPage {
  return {
    items: (data.items as CachedPayload[]).map(toProduct),
    total: Number(data.total),
  }
}

@Injectable()
export class CachedProductRepository implements ProductRepository {
  constructor(
    private readonly inner: ProductRepository,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly ttlSeconds: number = settings.cacheTtlSeconds,
  ) {}

  // -- ProductRepository ---------------------------------------------

  async listProducts(query: ProductQuery): Promise<ProductPage> {
    const key = listKey(query)
    const cached = await this.read(key, decodePage)
    if (cached !== null) {
      return cached
    }

    // Outside the guarded read/write: UnknownSortKeyError must propagate
    // uncached.
    const page = await this.inner.listProducts(query)
    await this.write(key, encodePage(page))
    return page
  }

  async getProduct(productId: string): Promise<Product | null> {
    const key = productKey(productId)
    const cached = await this.read(key, decodeProduct)
    if (cached !== null) {
      return cached
    }

    const product = await this.inner.getProduct(productId)
    if (product !== null) {
      await this.write(key, encodeProduct(product))
    }
    return product
  }

  async getProductDetail(productId: string): Promise<ProductDetail | null> {
    const key = productKey(productId)
    const cached = await this.read(key, decodeProductDetail)
    if (cached !== null) {
      return cached
    }

    const detail = await this.inner.getProductDetail(productId)
    if (detail !== null) {
      await this.write(key, encodeProduct(detail))
    }
    return detail
  }

  /** Delegates uncached: a handful of rows, one unbounded query. */
  async listCategories(): Promise<readonly Category[]> {
    return this.inner.listCategories()
  }

  // -- Redis, where any failure is a miss ------------------------------

  /**
   * Returns a decoded cache hit, or `null` for a miss of any cause.
   *
   * A miss, an outage, and a malformed or wrong-kind entry are all the same
   * outcome to the caller — ask the inner repository — so they collapse here
   * rather than at three call sites.
   */
  private async read<T>(
    key: string,
    decode: (data: CachedPayload) => T | null,
  ): Promise<T | null> {
    let raw: string | null
    try {
      raw = await this.redis.get(key)
    } catch (cause) {
      logger.warn('redis unavailable reading cache; falling back to source', {
        key,
        error: cause instanceof Error ? cause.message : String(cause),
      })
      return null
    }

    if (raw === null) {
      return null
    }
    try {
      return decode(JSON.parse(raw) as CachedPayload)
    } catch {
      logger.warn('discarding malformed cache entry', { key })
      return null
    }
  }

  private async write(key: string, value: string): Promise<void> {
    try {
      await this.redis.set(key, value, 'EX', this.ttlSeconds)
    } catch (cause) {
      logger.warn('redis unavailable writing cache; skipping cache write', {
        key,
        error: cause instanceof Error ? cause.message : String(cause),
      })
    }
  }
}
