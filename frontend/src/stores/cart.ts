/**
 * The Cart, mirrored from the server (ADR-001).
 *
 * The server owns the Cart; this store only reflects the most recent
 * `Cart` the API returned. `totalMinor` as displayed is always the number
 * the server sent last — an optimistic action may show a provisional total
 * for the moment between the local edit and the response landing, but the
 * server's number always wins the instant a response (success *or*
 * rollback-worthy failure) arrives.
 *
 * This is the single reader of `/api/cart` for the whole app: the header
 * badge, the product detail page's Add to Cart, and the cart view all go
 * through this store, so one action updates all three at once.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { apiClient } from '../api/client'
import type { ApiError, ApiResult, Cart } from '../types'

/** Path prefix for every Cart endpoint. `apiClient` prepends the API base URL. */
const CART_PATH = '/cart'

function itemPath(productId: string): string {
  return `${CART_PATH}/items/${encodeURIComponent(productId)}`
}

/**
 * A shallow-safe copy for rollback: a fresh `items` array of fresh line
 * objects, so an optimistic edit made after the snapshot (which mutates
 * `cart.value` in place via reassignment, never the snapshot itself) can
 * never leak back into it.
 */
function cloneCart(cart: Cart): Cart {
  return { ...cart, items: cart.items.map((item) => ({ ...item })) }
}

/** Client-side sum, used only to avoid a flash of the stale total during an
 * optimistic edit. Never trusted once a real response lands — see the
 * module comment above. */
function provisionalTotal(cart: Cart): number {
  return cart.items.reduce((sum, item) => sum + item.subtotalMinor, 0)
}

export const useCartStore = defineStore('cart', () => {
  /** The last `Cart` the server returned, or `undefined` before the first load. */
  const cart = ref<Cart | undefined>(undefined)

  /** True while the initial/refresh `GET /api/cart` is in flight. */
  const loadPending = ref(false)

  /** True while the mock checkout is running. */
  const checkoutPending = ref(false)

  /**
   * True while a request touching that specific line (add/change
   * quantity/remove) is in flight. Keyed by `productId` rather than a single
   * flag so changing one row does not disable every other row's controls.
   */
  const itemPending = ref<Record<string, boolean>>({})

  /** The failure from the most recent action, cleared when the next one starts. */
  const error = ref<ApiError | undefined>(undefined)

  const itemCount = computed(
    () => cart.value?.items.reduce((sum, item) => sum + item.quantity, 0) ?? 0,
  )

  function setItemPending(productId: string, value: boolean): void {
    // Reassigned rather than mutated so Pinia/Vue's reactivity picks up the
    // change reliably even though this is a plain object behind a `ref`.
    itemPending.value = { ...itemPending.value, [productId]: value }
  }

  /**
   * Applies an API result to the store.
   *
   * On success the server's Cart replaces local state wholesale — this is
   * the one place a response is allowed to win over whatever an optimistic
   * update guessed. On failure `cart` is deliberately left untouched here;
   * callers that applied an optimistic edit are responsible for restoring
   * their own snapshot.
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

  /** Loads the Cart for the current session. Safe to call on a cold session. */
  async function load(): Promise<ApiResult<Cart>> {
    loadPending.value = true
    error.value = undefined
    try {
      return apply(await apiClient.get<Cart>(CART_PATH))
    } finally {
      loadPending.value = false
    }
  }

  /**
   * Adds `quantity` of `productId`. Quantity must be >= 1; the API 422s
   * otherwise. Not applied optimistically: unlike a quantity change or a
   * removal, adding a brand-new line requires data (name, current price)
   * this store does not have client-side, so the row spinner is the only
   * optimistic feedback until the server's response lands.
   *
   * Name and signature are load-bearing: FE-03's product detail page calls
   * this exact `addItem(productId, quantity)`.
   */
  async function addItem(productId: string, quantity = 1): Promise<ApiResult<Cart>> {
    setItemPending(productId, true)
    error.value = undefined
    try {
      return apply(await apiClient.post<Cart>(`${CART_PATH}/items`, { productId, quantity }))
    } finally {
      setItemPending(productId, false)
    }
  }

  /**
   * Sets a line's quantity to exactly `quantity`, the entry point for the
   * cart view's quantity control. Applied optimistically: the row updates
   * the instant the shopper acts, and rolls back to the exact pre-action
   * Cart if the request fails.
   *
   * `quantity` < 1 is delegated to `removeItem` — the API returns 422 for a
   * `PATCH` of 0 rather than treating it as a delete, so a decrement from 1
   * must never reach this branch's `PATCH` call.
   */
  async function changeQuantity(productId: string, quantity: number): Promise<ApiResult<Cart>> {
    if (quantity < 1) {
      return removeItem(productId)
    }

    const current = cart.value
    if (!current) {
      // Nothing local to optimistically edit against (e.g. called before the
      // first load resolved) — fall through to a plain, non-optimistic PATCH.
      return runQuantityPatch(productId, quantity)
    }

    const previous = cloneCart(current)
    const items = current.items.map((item) =>
      item.productId === productId
        ? { ...item, quantity, subtotalMinor: item.unitPriceMinor * quantity }
        : item,
    )
    cart.value = { ...current, items, totalMinor: provisionalTotal({ ...current, items }) }

    setItemPending(productId, true)
    error.value = undefined
    try {
      const result = await runQuantityPatch(productId, quantity)
      if (!result.ok) {
        // Roll back to exactly the pre-action Cart; the server's rejection
        // means the optimistic guess above never actually happened.
        cart.value = previous
      }
      return result
    } finally {
      setItemPending(productId, false)
    }
  }

  function runQuantityPatch(productId: string, quantity: number): Promise<ApiResult<Cart>> {
    return apiClient.patch<Cart>(itemPath(productId), { quantity }).then(apply)
  }

  /**
   * Removes a line entirely. Applied optimistically like `changeQuantity`,
   * with the same snapshot-and-restore-on-failure rollback. A `DELETE` of a
   * product not present in the Cart is a 200 no-op on the server, so this is
   * also what a decrement from quantity 1 resolves to.
   */
  async function removeItem(productId: string): Promise<ApiResult<Cart>> {
    const current = cart.value
    const previous = current ? cloneCart(current) : undefined

    if (current) {
      const items = current.items.filter((item) => item.productId !== productId)
      cart.value = { ...current, items, totalMinor: provisionalTotal({ ...current, items }) }
    }

    setItemPending(productId, true)
    error.value = undefined
    try {
      const result = await apiClient.delete<Cart>(itemPath(productId))
      apply(result)
      if (!result.ok && previous) {
        cart.value = previous
      }
      return result
    } finally {
      setItemPending(productId, false)
    }
  }

  /**
   * Mock checkout (CONTEXT.md: "the mock act of converting a Cart into a
   * completed purchase. Nothing is charged and no order is stored"). BE-07
   * deliberately ships no order/checkout endpoint, and per ADR-002 there is
   * no authenticated Shopper for an order to belong to even if one existed —
   * so this clears the Cart client-side against the real, already-shipped
   * `DELETE` endpoint, one line at a time, rather than simulating a purchase
   * that nothing on the server actually records.
   *
   * Deletes are sequenced (not `Promise.all`) so `cart` always reflects a
   * Cart the server actually returned, one response at a time, and so a
   * mid-checkout failure leaves the store showing exactly the lines that
   * were — and were not — actually removed, rather than a guess.
   */
  async function checkout(): Promise<ApiResult<Cart>> {
    const current = cart.value
    if (!current || current.items.length === 0) {
      return current ? { ok: true, data: current } : load()
    }

    checkoutPending.value = true
    error.value = undefined
    let result: ApiResult<Cart> = { ok: true, data: current }
    try {
      for (const item of current.items) {
        setItemPending(item.productId, true)
        result = await apiClient.delete<Cart>(itemPath(item.productId))
        setItemPending(item.productId, false)
        if (!result.ok) {
          error.value = result.error
          return result
        }
        cart.value = result.data
      }
      return result
    } finally {
      checkoutPending.value = false
    }
  }

  return {
    cart,
    loadPending,
    checkoutPending,
    itemPending,
    error,
    itemCount,
    load,
    addItem,
    changeQuantity,
    removeItem,
    checkout,
  }
})
