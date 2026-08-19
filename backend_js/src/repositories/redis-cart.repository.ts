/**
 * Redis-backed `CartRepository`.
 *
 * Storage is deliberately minimal: `cart:{sessionId}` holds a JSON object of
 * `{productId: quantity}` and nothing else — never a name, price, or
 * currency. Every read and write re-resolves each line against
 * `ProductRepository`, which is what makes a catalogue price change visible in
 * an existing Cart and makes a stale serialized price impossible to serve,
 * since none is ever stored.
 *
 * `ProductRepository` is injected as the interface, not a concrete class, so
 * this module is independent of the Postgres-backed implementation and the
 * route tests can exercise it against `InMemoryRepository`.
 */

import { Inject, Injectable } from '@nestjs/common'
import type { Redis } from 'ioredis'

import { Cart, LineItem, makeLineItem } from '../domain/cart'
import { UnknownProductError } from '../domain/errors'
import { PRODUCT_REPOSITORY, CartRepository, ProductRepository } from '../domain/repositories'
import { REDIS_CLIENT } from '../redis/redis.constants'
import { settings } from '../config/settings'

const CART_KEY_PREFIX = 'cart:'

/**
 * Ceiling on a single line's quantity. Nothing about this storefront calls for
 * buying more than this of a single digital good, and without a ceiling a
 * single `POST /api/cart/items` with an absurd integer stores an equally
 * absurd value in Redis (and, downstream, in every rendered Cart's total).
 * Throwing — rather than clamping — matches the interface's convention for a
 * malformed quantity, and the HTTP layer maps it to 422 the same way it maps a
 * `quantity <= 0`.
 */
export const MAX_LINE_ITEM_QUANTITY = 1_000

/** The Redis key holding `sessionId`'s Cart. */
function cartKey(sessionId: string): string {
  return `${CART_KEY_PREFIX}${sessionId}`
}

function enforceQuantityCeiling(quantity: number): void {
  if (quantity > MAX_LINE_ITEM_QUANTITY) {
    throw new RangeError(
      `quantity must be <= ${MAX_LINE_ITEM_QUANTITY} (got ${quantity})`,
    )
  }
}

@Injectable()
export class RedisCartRepository implements CartRepository {
  constructor(
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    @Inject(PRODUCT_REPOSITORY) private readonly products: ProductRepository,
    private readonly ttlSeconds: number = settings.sessionTtlSeconds,
  ) {}

  // -- CartRepository -----------------------------------------------------

  async getCart(sessionId: string): Promise<Cart> {
    return this.render(sessionId, await this.readQuantities(sessionId))
  }

  async addItem(sessionId: string, productId: string, quantity: number): Promise<Cart> {
    if (quantity <= 0) {
      throw new RangeError('quantity must be > 0')
    }

    await this.requireProduct(productId)
    const quantities = await this.readQuantities(sessionId)
    const newQuantity = (quantities.get(productId) ?? 0) + quantity
    enforceQuantityCeiling(newQuantity)
    quantities.set(productId, newQuantity)
    await this.writeQuantities(sessionId, quantities)
    return this.render(sessionId, quantities)
  }

  async setQuantity(
    sessionId: string,
    productId: string,
    quantity: number,
  ): Promise<Cart> {
    if (quantity < 0) {
      throw new RangeError('quantity must be >= 0')
    }

    const quantities = await this.readQuantities(sessionId)
    if (quantity === 0) {
      quantities.delete(productId)
    } else {
      await this.requireProduct(productId)
      enforceQuantityCeiling(quantity)
      quantities.set(productId, quantity)
    }
    await this.writeQuantities(sessionId, quantities)
    return this.render(sessionId, quantities)
  }

  async removeItem(sessionId: string, productId: string): Promise<Cart> {
    const quantities = await this.readQuantities(sessionId)
    quantities.delete(productId)
    await this.writeQuantities(sessionId, quantities)
    return this.render(sessionId, quantities)
  }

  // -- storage --------------------------------------------------------

  /**
   * Reads the stored `{productId: quantity}` map, sliding the TTL.
   *
   * Absent, this returns an empty map rather than writing anything — an
   * unopened Cart never touches Redis beyond the read, matching
   * `InMemoryRepository.getCart`, which never populates its map until the
   * first write either.
   */
  private async readQuantities(sessionId: string): Promise<Map<string, number>> {
    const key = cartKey(sessionId)
    const raw = await this.redis.get(key)
    if (raw === null) {
      return new Map()
    }
    // Sliding TTL: a read is as much "activity" as a write, so a Shopper who
    // is only looking at their Cart does not have it expire out from under
    // them mid-session.
    await this.redis.expire(key, this.ttlSeconds)

    const data = JSON.parse(raw) as Record<string, number>
    return new Map(
      Object.entries(data).map(([productId, quantity]) => [
        String(productId),
        Math.trunc(Number(quantity)),
      ]),
    )
  }

  /**
   * Persists `{productId: quantity}`, or deletes the key once it is empty.
   *
   * `SET ... EX` sets the value and a fresh TTL in one command, keeping the
   * TTL sliding on writes exactly as it does on reads.
   */
  private async writeQuantities(
    sessionId: string,
    quantities: Map<string, number>,
  ): Promise<void> {
    const key = cartKey(sessionId)
    if (quantities.size === 0) {
      await this.redis.del(key)
      return
    }
    const payload = JSON.stringify(Object.fromEntries(quantities))
    await this.redis.set(key, payload, 'EX', this.ttlSeconds)
  }

  // -- rendering --------------------------------------------------------

  /**
   * Builds a `Cart` from stored quantities, re-reading every price.
   *
   * A product id with no matching row in `ProductRepository` — deleted from
   * the catalogue since it was added — is silently dropped from the rendered
   * Cart rather than raising, so one vanished product does not lock a Shopper
   * out of the rest of their Cart. The dangling quantity is left in Redis
   * rather than rewritten here, since this backs both the write paths (which
   * already persisted their own change) and the pure-read `getCart` (which
   * must not turn a read into a write).
   */
  private async render(
    sessionId: string,
    quantities: Map<string, number>,
  ): Promise<Cart> {
    const items: LineItem[] = []
    for (const [productId, quantity] of quantities) {
      const product = await this.products.getProduct(productId)
      if (product === null) {
        continue
      }
      items.push(makeLineItem(product, quantity))
    }
    return { sessionId, items }
  }

  private async requireProduct(productId: string): Promise<void> {
    if ((await this.products.getProduct(productId)) === null) {
      throw new UnknownProductError(productId)
    }
  }
}
