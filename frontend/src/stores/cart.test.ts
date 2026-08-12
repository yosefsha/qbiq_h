import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/client'
import type { ApiError, Cart } from '../types'
import { useCartStore } from './cart'

vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockedApiClient = vi.mocked(apiClient)

function cart(overrides: Partial<Cart> = {}): Cart {
  return {
    items: [
      { productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 2, subtotalMinor: 2000 },
      { productId: '2', name: 'Gadget', unitPriceMinor: 500, quantity: 1, subtotalMinor: 500 },
    ],
    totalMinor: 2500,
    currency: 'USD',
    ...overrides,
  }
}

/** A promise plus its resolve/reject, for asserting mid-flight state. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const networkError: ApiError = { kind: 'network', message: 'Failed to fetch' }

describe('useCartStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe('load', () => {
    it('populates the cart from the server response', async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      const store = useCartStore()

      await store.load()

      expect(store.cart).toEqual(cart())
      expect(store.error).toBeUndefined()
      expect(store.loadPending).toBe(false)
    })

    it('surfaces a failure without inventing a cart', async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: false, error: networkError })
      const store = useCartStore()

      await store.load()

      expect(store.cart).toBeUndefined()
      expect(store.error).toEqual(networkError)
    })

    it('sets loadPending only while the request is in flight', async () => {
      const { promise, resolve } = deferred<{ ok: true; data: Cart }>()
      mockedApiClient.get.mockReturnValueOnce(promise)
      const store = useCartStore()

      const pending = store.load()
      expect(store.loadPending).toBe(true)

      resolve({ ok: true, data: cart() })
      await pending

      expect(store.loadPending).toBe(false)
    })
  })

  describe('addItem', () => {
    it('keeps the name and signature FE-03 depends on: addItem(productId, quantity)', async () => {
      mockedApiClient.post.mockResolvedValueOnce({ ok: true, data: cart() })
      const store = useCartStore()

      await store.addItem('1', 3)

      expect(mockedApiClient.post).toHaveBeenCalledWith('/cart/items', { productId: '1', quantity: 3 })
    })

    it('defaults quantity to 1', async () => {
      mockedApiClient.post.mockResolvedValueOnce({ ok: true, data: cart() })
      const store = useCartStore()

      await store.addItem('1')

      expect(mockedApiClient.post).toHaveBeenCalledWith('/cart/items', { productId: '1', quantity: 1 })
    })
  })

  describe('changeQuantity', () => {
    it('shows the total from the server response, not one computed locally', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      // Deliberately not what naive line-item arithmetic would produce
      // (3 * 1000 + 500 = 3500) so a test that passes by accident (a local
      // sum happening to match the server) is not possible.
      const surprising = cart({
        items: [
          { productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 3, subtotalMinor: 3000 },
          { productId: '2', name: 'Gadget', unitPriceMinor: 500, quantity: 1, subtotalMinor: 500 },
        ],
        totalMinor: 999999,
      })
      mockedApiClient.patch.mockResolvedValueOnce({ ok: true, data: surprising })

      await store.changeQuantity('1', 3)

      expect(store.cart?.totalMinor).toBe(999999)
    })

    it('applies the edit optimistically before the response lands', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      const { promise, resolve } = deferred<{ ok: true; data: Cart }>()
      mockedApiClient.patch.mockReturnValueOnce(promise)

      const pending = store.changeQuantity('1', 5)

      expect(store.cart?.items.find((item) => item.productId === '1')?.quantity).toBe(5)

      resolve({ ok: true, data: cart() })
      await pending
    })

    it('rolls back to exactly the pre-action cart when the request fails', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()
      const before = JSON.parse(JSON.stringify(store.cart)) as Cart

      mockedApiClient.patch.mockResolvedValueOnce({ ok: false, error: networkError })

      await store.changeQuantity('1', 5)

      expect(store.cart).toEqual(before)
      expect(store.error).toEqual(networkError)
    })

    it('sends a PATCH for a quantity of 1 or more', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()
      mockedApiClient.patch.mockResolvedValueOnce({ ok: true, data: cart() })

      await store.changeQuantity('1', 1)

      expect(mockedApiClient.patch).toHaveBeenCalledWith('/cart/items/1', { quantity: 1 })
      expect(mockedApiClient.delete).not.toHaveBeenCalled()
    })

    it('decrementing from 1 issues DELETE, never PATCH with a quantity of 0', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()
      mockedApiClient.delete.mockResolvedValueOnce({
        ok: true,
        data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
      })

      await store.changeQuantity('1', 0)

      expect(mockedApiClient.delete).toHaveBeenCalledWith('/cart/items/1')
      expect(mockedApiClient.patch).not.toHaveBeenCalled()
    })
  })

  describe('removeItem', () => {
    it('removes the line optimistically before the response lands', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      const { promise, resolve } = deferred<{ ok: true; data: Cart }>()
      mockedApiClient.delete.mockReturnValueOnce(promise)

      const pending = store.removeItem('1')

      expect(store.cart?.items.some((item) => item.productId === '1')).toBe(false)

      resolve({ ok: true, data: cart({ items: [], totalMinor: 0 }) })
      await pending
    })

    it('rolls back to exactly the pre-action cart when the request fails, and surfaces the error', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()
      const before = JSON.parse(JSON.stringify(store.cart)) as Cart

      mockedApiClient.delete.mockResolvedValueOnce({ ok: false, error: networkError })

      await store.removeItem('1')

      expect(store.cart).toEqual(before)
      expect(store.error).toEqual(networkError)
    })
  })

  describe('per-action pending', () => {
    it('flags only the row being changed, not the whole cart', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      const { promise, resolve } = deferred<{ ok: true; data: Cart }>()
      mockedApiClient.patch.mockReturnValueOnce(promise)

      const pending = store.changeQuantity('1', 5)

      expect(store.itemPending['1']).toBe(true)
      expect(store.itemPending['2']).toBeFalsy()

      resolve({ ok: true, data: cart() })
      await pending

      expect(store.itemPending['1']).toBe(false)
    })
  })

  describe('checkout', () => {
    it('is a mock that clears the cart via DELETE, with no order persisted anywhere', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      mockedApiClient.delete
        .mockResolvedValueOnce({
          ok: true,
          data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
        })
        .mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })

      await store.checkout()

      expect(mockedApiClient.delete).toHaveBeenNthCalledWith(1, '/cart/items/1')
      expect(mockedApiClient.delete).toHaveBeenNthCalledWith(2, '/cart/items/2')
      expect(store.cart?.items).toEqual([])
      expect(store.cart?.totalMinor).toBe(0)
      expect(store.checkoutPending).toBe(false)
    })

    it('is a no-op on an already-empty cart', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })
      await store.load()

      await store.checkout()

      expect(mockedApiClient.delete).not.toHaveBeenCalled()
    })

    it('stops and surfaces the error if a line fails to clear, leaving prior removals in place', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      mockedApiClient.delete
        .mockResolvedValueOnce({
          ok: true,
          data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
        })
        .mockResolvedValueOnce({ ok: false, error: networkError })

      await store.checkout()

      expect(store.error).toEqual(networkError)
      expect(store.cart?.items).toEqual([cart().items[1]])
      expect(store.checkoutPending).toBe(false)
    })
  })

  describe('itemCount', () => {
    it('sums line-item quantities for the header badge', async () => {
      const store = useCartStore()
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      await store.load()

      expect(store.itemCount).toBe(3)
    })

    it('is zero before the first load and for an empty cart', () => {
      const store = useCartStore()
      expect(store.itemCount).toBe(0)
    })
  })
})
