/**
 * The Cart, mirrored from the server (ADR-001).
 *
 * The server owns the Cart; this store only reflects the most recent
 * `CartView` the API returned. Every action writes the server's response
 * straight into `cart` — nothing here computes a total, adjusts a quantity
 * locally, or persists anything. `totalMinor` as displayed is always the
 * number the server sent, so the two can never disagree.
 *
 * This is the single reader of `/api/cart` for the whole app: the header
 * badge, the product detail page's Add to Cart, and the cart view all go
 * through this store, so one action updates all three at once.
 *
 * Scope note: this is the shared skeleton, added ahead of FE-02/FE-03/FE-04
 * so the detail page's Add to Cart and the cart view code against one store
 * rather than each inventing its own. FE-04 owns it from here and is expected
 * to extend it — optimistic updates with rollback, per-action pending state
 * finer than the single `pending` flag below, and the mock checkout.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { apiClient } from '../api/client'
import type { ApiError, ApiResult, Cart } from '../types'

/** Path prefix for every Cart endpoint. `apiClient` prepends the API base URL. */
const CART_PATH = '/cart'

export const useCartStore = defineStore('cart', () => {
  /** The last `CartView` the server returned, or `undefined` before the first load. */
  const cart = ref<Cart | undefined>(undefined)

  /** True while any Cart request is in flight. */
  const pending = ref(false)

  /** The failure from the most recent action, cleared when the next one starts. */
  const error = ref<ApiError | undefined>(undefined)

  /**
   * Applies an API result to the store.
   *
   * On success the server's Cart replaces local state wholesale. On failure
   * `cart` is deliberately left untouched: a failed quantity change should
   * leave the Shopper looking at the Cart they still have, not an empty one.
   */
  function apply(result: ApiResult<Cart>): ApiResult<Cart> {
    if (result.ok) {
      cart.value = result.data
      error.value = undefined
    } else {
      error.value = result.error
    }
    return result
  }

  async function run(request: () => Promise<ApiResult<Cart>>): Promise<ApiResult<Cart>> {
    pending.value = true
    error.value = undefined
    try {
      return apply(await request())
    } finally {
      pending.value = false
    }
  }

  /** Loads the Cart for the current session. Safe to call on a cold session. */
  function load(): Promise<ApiResult<Cart>> {
    return run(() => apiClient.get<Cart>(CART_PATH))
  }

  /** Adds `quantity` of `productId`. Quantity must be >= 1; the API 422s otherwise. */
  function addItem(productId: string, quantity = 1): Promise<ApiResult<Cart>> {
    return run(() => apiClient.post<Cart>(`${CART_PATH}/items`, { productId, quantity }))
  }

  /**
   * Sets a line's quantity to exactly `quantity`.
   *
   * `quantity` must be >= 1. Removal is `removeItem`, not a quantity of zero —
   * the API returns 422 for a `PATCH` to 0 rather than treating it as a delete.
   */
  function setQuantity(productId: string, quantity: number): Promise<ApiResult<Cart>> {
    return run(() =>
      apiClient.patch<Cart>(`${CART_PATH}/items/${encodeURIComponent(productId)}`, { quantity }),
    )
  }

  /** Removes a line entirely. A no-op on the server if it was not present. */
  function removeItem(productId: string): Promise<ApiResult<Cart>> {
    return run(() =>
      apiClient.delete<Cart>(`${CART_PATH}/items/${encodeURIComponent(productId)}`),
    )
  }

  return { cart, pending, error, load, addItem, setQuantity, removeItem }
})
