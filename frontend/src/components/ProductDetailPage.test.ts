import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Router } from 'vue-router'

import { apiClient } from '../api/client'
import { useCartStore } from '../stores/cart'
import type { ApiResult, Cart, ProductDetail } from '../types'
import ProductDetailPage from './ProductDetailPage.vue'

function makeProduct(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    id: '1',
    name: 'Test Product',
    priceMinor: 14900,
    currency: 'USD',
    shortDescription: 'A short description.',
    thumbnailUrl: 'https://example.com/thumb.jpg',
    category: { slug: 'books', name: 'Books' },
    longDescription: 'A much longer description of the product.',
    reviews: [{ id: 'r1', author: 'Ada', rating: 5, body: 'Great product!' }],
    ...overrides,
  }
}

function makeCart(overrides: Partial<Cart> = {}): Cart {
  return { items: [], totalMinor: 0, currency: 'USD', ...overrides }
}

async function mountPage(id = '1'): Promise<{ wrapper: ReturnType<typeof mount>; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'catalogue', component: { template: '<div />' } },
      { path: '/products/:id', name: 'product-detail', component: ProductDetailPage, props: true },
    ],
  })
  await router.push(`/products/${id}`)
  await router.isReady()

  const wrapper = mount(ProductDetailPage, {
    props: { id },
    global: { plugins: [router] },
  })
  await flushPromises()

  return { wrapper, router }
}

describe('ProductDetailPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('renders a not-found state for an unknown product id, not a crash or blank page', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      ok: false,
      error: { kind: 'http', status: 404, message: 'Product not found' },
    })

    const { wrapper } = await mountPage('999')

    expect(wrapper.text()).toContain('Not found')
    expect(wrapper.text()).toContain('Product not found')
    // The not-found presentation is not retryable, so no retry button.
    expect(wrapper.find('[data-error-kind]').find('button').exists()).toBe(false)
  })

  it('renders the long description, category, price and reviews on a successful load', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct() })

    const { wrapper } = await mountPage('1')

    expect(wrapper.text()).toContain('A much longer description of the product.')
    expect(wrapper.text()).toContain('Books')
    expect(wrapper.text()).toContain('$149.00')
    expect(wrapper.text()).toContain('Ada')
    expect(wrapper.text()).toContain('Great product!')
    expect(wrapper.text()).not.toContain('No reviews yet')
  })

  it('renders an explicit empty state when a product has no reviews', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct({ reviews: [] }) })

    const { wrapper } = await mountPage('1')

    expect(wrapper.find('[data-testid="reviews-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('No reviews yet')
  })

  it('renders a review list when a product has several reviews', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      ok: true,
      data: makeProduct({
        reviews: [
          { id: 'r1', author: 'Ada', rating: 5, body: 'Loved it.' },
          { id: 'r2', author: 'Grace', rating: 4, body: 'Pretty good.' },
          { id: 'r3', author: 'Alan', rating: 3, body: 'It was fine.' },
        ],
      }),
    })

    const { wrapper } = await mountPage('1')

    expect(wrapper.findAll('li')).toHaveLength(3)
    expect(wrapper.find('[data-testid="reviews-empty"]').exists()).toBe(false)
  })

  it('shows a pending state while Add to Cart is in flight, then a success message', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct({ id: '1' }) })

    let resolvePost!: (value: ApiResult<Cart>) => void
    const pending = new Promise<ApiResult<Cart>>((resolve) => {
      resolvePost = resolve
    })
    vi.spyOn(apiClient, 'post').mockReturnValue(pending)

    const { wrapper } = await mountPage('1')

    const addButton = wrapper.get('[data-testid="add-to-cart-button"]')
    void addButton.trigger('click')
    await flushPromises()

    expect(addButton.attributes('disabled')).toBeDefined()
    expect(addButton.text()).toContain('Adding')

    resolvePost({
      ok: true,
      data: makeCart({ items: [{ productId: '1', name: 'Test Product', unitPriceMinor: 14900, quantity: 1, subtotalMinor: 14900 }] }),
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="add-to-cart-button"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('Added to cart.')
  })

  it('surfaces a visible error when Add to Cart fails', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct() })
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      ok: false,
      error: { kind: 'http', status: 422, message: 'Quantity must be at least 1' },
    })

    const { wrapper } = await mountPage('1')

    await wrapper.get('[data-testid="add-to-cart-button"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Quantity must be at least 1')
    expect(wrapper.text()).not.toContain('Added to cart.')
  })

  it('calls the cart store, not apiClient, with the product id and quantity', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct({ id: '7' }) })
    const cartStore = useCartStore()
    const addItemSpy = vi.spyOn(cartStore, 'addItem').mockResolvedValue({ ok: true, data: makeCart() })
    const postSpy = vi.spyOn(apiClient, 'post')

    const { wrapper } = await mountPage('7')

    await wrapper.get('[data-testid="add-to-cart-button"]').trigger('click')
    await flushPromises()

    expect(addItemSpy).toHaveBeenCalledWith('7', 1)
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('falls back to the catalogue root when opened as a deep link with no history', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct() })
    window.history.replaceState(
      { back: null, current: '/products/1', forward: null, position: 0, replaced: true, scroll: null },
      '',
    )

    const { wrapper, router } = await mountPage('1')
    const pushSpy = vi.spyOn(router, 'push')
    const backSpy = vi.spyOn(router, 'back').mockImplementation(() => {})

    await wrapper.get('[data-testid="back-to-products-button"]').trigger('click')

    expect(pushSpy).toHaveBeenCalledWith('/')
    expect(backSpy).not.toHaveBeenCalled()
  })

  it('goes back, preserving filters, when the previous entry was the catalogue', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ ok: true, data: makeProduct() })
    window.history.replaceState(
      {
        back: '/?category=books',
        current: '/products/1',
        forward: null,
        position: 1,
        replaced: true,
        scroll: null,
      },
      '',
    )

    const { wrapper, router } = await mountPage('1')
    const pushSpy = vi.spyOn(router, 'push')
    const backSpy = vi.spyOn(router, 'back').mockImplementation(() => {})

    await wrapper.get('[data-testid="back-to-products-button"]').trigger('click')

    expect(backSpy).toHaveBeenCalledTimes(1)
    expect(pushSpy).not.toHaveBeenCalled()
  })
})
