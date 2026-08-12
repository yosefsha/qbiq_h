import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { apiClient } from '../api/client'
import { useCartStore } from '../stores/cart'
import type { ApiError, Cart } from '../types'
import CartPage from './CartPage.vue'

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

const networkError: ApiError = { kind: 'network', message: 'Failed to fetch' }

async function mountCartPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'catalogue', component: { template: '<div />' } },
      { path: '/cart', name: 'cart', component: CartPage },
    ],
  })
  await router.push('/cart')
  await router.isReady()

  return mount(CartPage, { global: { plugins: [router] } })
}

describe('CartPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads and renders line items with name, unit price, quantity, subtotal, and the server total', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
    const wrapper = await mountCartPage()
    await flushPromises()

    const rows = wrapper.findAll('li')
    expect(rows).toHaveLength(2)
    expect(wrapper.text()).toContain('Widget')
    expect(wrapper.text()).toContain('$10.00 each')
    expect(wrapper.text()).toContain('$20.00')
    expect(wrapper.find('[data-test="cart-total"]').text()).toBe('$25.00')
    expect(wrapper.find('[data-test="checkout"]').exists()).toBe(true)
  })

  it('renders a deliberate empty state, not a bare "0 items"', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })
    const wrapper = await mountCartPage()
    await flushPromises()

    expect(wrapper.find('[data-test="empty-cart"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Your cart is empty')
    expect(wrapper.text()).not.toContain('0 items')
  })

  it('surfaces a load failure via ErrorState', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: false, error: networkError })
    const wrapper = await mountCartPage()
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("Can't reach the server")
  })

  it('shows the total from the server response after a quantity change, not local arithmetic', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
    const wrapper = await mountCartPage()
    await flushPromises()

    // Deliberately not what 3 * 1000 + 500 would produce, so the assertion
    // below can only pass if the UI is rendering the server's number.
    const surprising = cart({
      items: [
        { productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 3, subtotalMinor: 3000 },
        { productId: '2', name: 'Gadget', unitPriceMinor: 500, quantity: 1, subtotalMinor: 500 },
      ],
      totalMinor: 777777,
    })
    mockedApiClient.patch.mockResolvedValueOnce({ ok: true, data: surprising })

    const increment = wrapper.find('[data-product-id="1"] [aria-label="Increase quantity of Widget"]')
    await increment.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="cart-total"]').text()).toBe('$7,777.77')
  })

  it('decrementing from quantity 1 issues DELETE, never a PATCH with 0', async () => {
    mockedApiClient.get.mockResolvedValueOnce({
      ok: true,
      data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
    })
    const wrapper = await mountCartPage()
    await flushPromises()

    mockedApiClient.delete.mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })

    const decrement = wrapper.find('[data-product-id="2"] [aria-label="Decrease quantity of Gadget"]')
    await decrement.trigger('click')
    await flushPromises()

    expect(mockedApiClient.delete).toHaveBeenCalledWith('/cart/items/2')
    expect(mockedApiClient.patch).not.toHaveBeenCalled()
  })

  it('the remove control removes the line', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
    const wrapper = await mountCartPage()
    await flushPromises()

    mockedApiClient.delete.mockResolvedValueOnce({
      ok: true,
      data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
    })

    const removeButtons = wrapper.findAll('button').filter((button) => button.text() === 'Remove')
    await removeButtons[0]!.trigger('click')
    await flushPromises()

    expect(mockedApiClient.delete).toHaveBeenCalledWith('/cart/items/1')
  })

  it('checkout clears the cart', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
    const wrapper = await mountCartPage()
    await flushPromises()

    mockedApiClient.delete
      .mockResolvedValueOnce({
        ok: true,
        data: cart({ items: [cart().items[1]!], totalMinor: 500 }),
      })
      .mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })

    await wrapper.find('[data-test="checkout"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="empty-cart"]').exists()).toBe(true)
  })

  it('disables only the row being changed while its request is in flight', async () => {
    mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
    const wrapper = await mountCartPage()
    await flushPromises()

    let resolvePatch!: (value: { ok: true; data: Cart }) => void
    mockedApiClient.patch.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePatch = resolve
      }),
    )

    const row1Increment = wrapper.find('[data-product-id="1"] [aria-label="Increase quantity of Widget"]')
    const row2Increment = wrapper.find('[data-product-id="2"] [aria-label="Increase quantity of Gadget"]')

    await row1Increment.trigger('click')
    await wrapper.vm.$nextTick()

    expect(row1Increment.attributes('disabled')).toBeDefined()
    expect(row2Increment.attributes('disabled')).toBeUndefined()

    resolvePatch({ ok: true, data: cart() })
    await flushPromises()
  })

  it('reads the store the app already loaded, without fetching again', async () => {
    setActivePinia(createPinia())
    const store = useCartStore()
    store.cart = cart()

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'catalogue', component: { template: '<div />' } },
        { path: '/cart', name: 'cart', component: CartPage },
      ],
    })
    await router.push('/cart')
    await router.isReady()
    mount(CartPage, { global: { plugins: [router] } })
    await flushPromises()

    expect(mockedApiClient.get).not.toHaveBeenCalled()
  })

  describe('accessibility', () => {
    it("names each row's quantity and remove controls with the item, not the generic \"Increase quantity\"", async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      const wrapper = await mountCartPage()
      await flushPromises()

      const row = wrapper.get('[data-product-id="1"]')
      expect(row.find('[aria-label="Increase quantity of Widget"]').exists()).toBe(true)
      expect(row.find('[aria-label="Decrease quantity of Widget"]').exists()).toBe(true)
      expect(row.find('[aria-label="Remove Widget from cart"]').exists()).toBe(true)
    })

    it('announces the cart summary through a single polite live region', async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart() })
      const wrapper = await mountCartPage()
      await flushPromises()

      const liveRegions = wrapper.findAll('[aria-live="polite"]')
      expect(liveRegions).toHaveLength(1)
      expect(liveRegions[0]?.text()).toBe('3 items in your cart. Total $25.00.')
    })

    it('announces the empty cart through that same live region', async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: true, data: cart({ items: [], totalMinor: 0 }) })
      const wrapper = await mountCartPage()
      await flushPromises()

      expect(wrapper.get('[aria-live="polite"]').text()).toBe('Your cart is empty.')
    })

    it('leaves the live region empty on a load failure so it does not talk over ErrorState\'s role="alert"', async () => {
      mockedApiClient.get.mockResolvedValueOnce({ ok: false, error: networkError })
      const wrapper = await mountCartPage()
      await flushPromises()

      expect(wrapper.get('[aria-live="polite"]').text()).toBe('')
      expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    })
  })
})
