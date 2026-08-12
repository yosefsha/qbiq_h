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
})
