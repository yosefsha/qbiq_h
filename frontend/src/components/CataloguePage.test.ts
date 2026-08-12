import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { apiClient } from '../api/client'
import type { ApiResult, Category, ProductPage } from '../types'
import CataloguePage from './CataloguePage.vue'
import ErrorState from './ErrorState.vue'

vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

const getMock = vi.mocked(apiClient.get)

function page(overrides: Partial<ProductPage> = {}): ProductPage {
  return {
    items: [
      {
        id: '1',
        name: 'Deep Work',
        priceMinor: 14900,
        currency: 'USD',
        shortDescription: 'A guide to focused success.',
        thumbnailUrl: 'https://cdn.example.com/deep-work.jpg',
        category: { slug: 'books', name: 'Books' },
      },
    ],
    total: 1,
    limit: 12,
    offset: 0,
    ...overrides,
  }
}

const categories: Category[] = [
  { slug: 'books', name: 'Books' },
  { slug: 'software', name: 'Software' },
]

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** Routes every `/categories` call to a resolved empty list, and every `/products` call to `resolveProducts`. */
function stubApi(resolveProducts: () => Promise<ApiResult<ProductPage>>): void {
  getMock.mockImplementation((path: string) => {
    if (path.startsWith('/categories')) {
      return Promise.resolve({ ok: true, data: categories })
    }
    return resolveProducts()
  })
}

async function mountCataloguePage(initialPath = '/'): Promise<{
  wrapper: VueWrapper
  router: Router
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'catalogue', component: CataloguePage },
      { path: '/products/:id', name: 'product-detail', component: { template: '<div />' } },
    ],
  })
  await router.push(initialPath)
  await router.isReady()

  const wrapper = mount(CataloguePage, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()

  return { wrapper, router }
}

describe('CataloguePage', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders skeleton loaders while the initial request is in flight, not a bare spinner', async () => {
    const productsDeferred = deferred<ApiResult<ProductPage>>()
    stubApi(() => productsDeferred.promise)

    const { wrapper } = await mountCataloguePage()

    const skeleton = wrapper.find('[data-testid="catalogue-skeleton"]')
    expect(skeleton.exists()).toBe(true)
    expect(wrapper.find('[data-testid="catalogue-empty"]').exists()).toBe(false)
    expect(wrapper.findComponent(ErrorState).exists()).toBe(false)

    productsDeferred.resolve({ ok: true, data: page() })
    await flushPromises()

    expect(wrapper.find('[data-testid="catalogue-skeleton"]').exists()).toBe(false)
  })

  it('renders products with a price formatted via Intl.NumberFormat from minor units', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page() }))

    const { wrapper } = await mountCataloguePage()

    expect(wrapper.text()).toContain('Deep Work')
    expect(wrapper.text()).toContain('$149.00')
    const link = wrapper.find('a[href="/products/1"]')
    expect(link.exists()).toBe(true)
  })

  it('renders an empty state, distinct from an error, when the query matches nothing', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page({ items: [], total: 0 }) }))

    const { wrapper } = await mountCataloguePage()

    expect(wrapper.find('[data-testid="catalogue-empty"]').exists()).toBe(true)
    expect(wrapper.findComponent(ErrorState).exists()).toBe(false)
  })

  it('renders ErrorState, not an empty list, when the request fails', async () => {
    stubApi(() =>
      Promise.resolve({
        ok: false,
        error: { kind: 'http', status: 500, message: 'Internal Server Error' },
      }),
    )

    const { wrapper } = await mountCataloguePage()

    expect(wrapper.find('[data-testid="catalogue-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="catalogue-skeleton"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Request failed (500)')
  })

  it('renders ErrorState, not an empty list, for a 422 from an unknown category', async () => {
    stubApi(() =>
      Promise.resolve({
        ok: false,
        error: { kind: 'http', status: 422, message: "Unknown category: 'not-real'" },
      }),
    )

    const { wrapper } = await mountCataloguePage('/?category=not-real')

    expect(wrapper.find('[data-testid="catalogue-empty"]').exists()).toBe(false)
    expect(wrapper.text()).toContain("Unknown category: 'not-real'")
  })

  it('restores name/category/sort/direction from the URL on mount and issues the matching request', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page() }))

    await mountCataloguePage('/?name=flow&category=software&sort=price&direction=desc')

    const productsCall = getMock.mock.calls.find(([path]) => path.startsWith('/products'))
    expect(productsCall?.[0]).toBe(
      '/products?name=flow&category=software&sort=price&direction=desc&limit=12&offset=0',
    )
  })

  it('debounces the name filter and sends a single request for the settled value', async () => {
    vi.useFakeTimers()
    stubApi(() => Promise.resolve({ ok: true, data: page() }))

    const { wrapper } = await mountCataloguePage()
    getMock.mockClear()

    const input = wrapper.get('#catalogue-name-filter')
    await input.setValue('f')
    await input.setValue('fl')
    await input.setValue('flow')

    // Not yet — still within the debounce window.
    expect(getMock).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    const productsCalls = getMock.mock.calls.filter(([path]) => path.startsWith('/products'))
    expect(productsCalls).toHaveLength(1)
    expect(productsCalls[0]?.[0]).toBe('/products?name=flow&limit=12&offset=0')
  })

  it('updates the URL query params when a filter changes, so the view is shareable', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page() }))

    const { wrapper, router } = await mountCataloguePage()

    const categorySelect = wrapper.get('#catalogue-category-filter')
    await categorySelect.setValue('software')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ category: 'software' })
  })

  it('changing sort issues a new request with sort and direction', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page() }))

    const { wrapper } = await mountCataloguePage()
    getMock.mockClear()

    const sortSelect = wrapper.get('#catalogue-sort')
    await sortSelect.setValue('price-desc')
    await flushPromises()

    const productsCalls = getMock.mock.calls.filter(([path]) => path.startsWith('/products'))
    expect(productsCalls[0]?.[0]).toBe('/products?sort=price&direction=desc&limit=12&offset=0')
  })

  it('paginates using limit/offset and the returned total, disabling Previous on the first page', async () => {
    stubApi(() => Promise.resolve({ ok: true, data: page({ total: 30 }) }))

    const { wrapper } = await mountCataloguePage()

    const [previousButton, nextButton] = wrapper.findAll('button')
    expect(previousButton?.attributes('disabled')).toBeDefined()
    expect(nextButton?.attributes('disabled')).toBeUndefined()

    getMock.mockClear()
    await nextButton?.trigger('click')
    await flushPromises()

    const productsCalls = getMock.mock.calls.filter(([path]) => path.startsWith('/products'))
    expect(productsCalls[0]?.[0]).toBe('/products?limit=12&offset=12')
  })
})
