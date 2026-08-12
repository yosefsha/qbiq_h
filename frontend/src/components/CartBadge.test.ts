import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/client'
import { useCartStore } from '../stores/cart'
import type { Cart } from '../types'
import CartBadge from './CartBadge.vue'

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
    ],
    totalMinor: 2000,
    currency: 'USD',
    ...overrides,
  }
}

describe('CartBadge', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders nothing before the store has a cart', () => {
    const wrapper = mount(CartBadge)

    expect(wrapper.find('[data-test="cart-badge-count"]').exists()).toBe(false)
  })

  it('reflects the item count already in the store, without fetching itself', () => {
    const store = useCartStore()
    store.cart = cart({
      items: [
        { productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 2, subtotalMinor: 2000 },
        { productId: '2', name: 'Gadget', unitPriceMinor: 500, quantity: 3, subtotalMinor: 1500 },
      ],
    })

    const wrapper = mount(CartBadge)

    expect(wrapper.find('[data-test="cart-badge-count"]').text()).toBe('5')
    expect(mockedApiClient.get).not.toHaveBeenCalled()
  })

  it('updates reactively when the store changes elsewhere (e.g. after checkout)', async () => {
    const store = useCartStore()
    store.cart = cart()
    const wrapper = mount(CartBadge)
    expect(wrapper.find('[data-test="cart-badge-count"]').exists()).toBe(true)

    store.cart = cart({ items: [], totalMinor: 0 })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-test="cart-badge-count"]').exists()).toBe(false)
  })

  describe('accessibility', () => {
    it('gives screen readers item-count context beyond the bare number, for the "Cart" link it sits inside', () => {
      const store = useCartStore()
      store.cart = cart({
        items: [
          { productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 2, subtotalMinor: 2000 },
          { productId: '2', name: 'Gadget', unitPriceMinor: 500, quantity: 3, subtotalMinor: 1500 },
        ],
      })

      const wrapper = mount(CartBadge)

      // The visible number alone ("5") is ambiguous out of context; this
      // text is what actually reaches the accessible name of the enclosing
      // "Cart" link (App.vue), e.g. "Cart, 5 items".
      expect(wrapper.text()).toContain('5 items')
    })

    it('hides the bare visible number from assistive tech, since the sr-only text already covers it', () => {
      const store = useCartStore()
      store.cart = cart()

      const wrapper = mount(CartBadge)

      expect(wrapper.get('[data-test="cart-badge-count"]').attributes('aria-hidden')).toBe('true')
    })

    it('uses the singular "item" for a single item', () => {
      const store = useCartStore()
      store.cart = cart({
        items: [{ productId: '1', name: 'Widget', unitPriceMinor: 1000, quantity: 1, subtotalMinor: 1000 }],
      })

      const wrapper = mount(CartBadge)

      expect(wrapper.text()).toContain('1 item')
      expect(wrapper.text()).not.toContain('1 items')
    })
  })
})
