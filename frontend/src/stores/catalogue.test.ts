import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/client'
import type { ApiResult, Category, ProductPage } from '../types'
import { useCatalogueStore } from './catalogue'

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
        priceMinor: 1999,
        currency: 'USD',
        shortDescription: 'Focus.',
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

describe('useCatalogueStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMock.mockReset()
  })

  it('fetches products with limit/offset and no other filters by default', async () => {
    getMock.mockResolvedValueOnce({ ok: true, data: page() })
    const store = useCatalogueStore()

    await store.fetchProducts()

    expect(getMock).toHaveBeenCalledExactlyOnceWith('/products?limit=12&offset=0')
    expect(store.items).toEqual(page().items)
    expect(store.total).toBe(1)
    expect(store.error).toBeUndefined()
  })

  it('issues a new request with the updated query string when a filter changes', async () => {
    getMock.mockResolvedValue({ ok: true, data: page() })
    const store = useCatalogueStore()
    await store.fetchProducts()

    await store.updateQuery({ name: 'flow' })

    expect(getMock).toHaveBeenLastCalledWith('/products?name=flow&limit=12&offset=0')
  })

  it('issues a new request when the category filter changes', async () => {
    getMock.mockResolvedValue({ ok: true, data: page() })
    const store = useCatalogueStore()
    await store.fetchProducts()

    await store.updateQuery({ category: 'software' })

    expect(getMock).toHaveBeenLastCalledWith('/products?category=software&limit=12&offset=0')
  })

  it('issues a new request when sort/direction changes', async () => {
    getMock.mockResolvedValue({ ok: true, data: page() })
    const store = useCatalogueStore()
    await store.fetchProducts()

    await store.updateQuery({ sort: 'price', direction: 'desc' })

    expect(getMock).toHaveBeenLastCalledWith(
      '/products?sort=price&direction=desc&limit=12&offset=0',
    )
  })

  it('resets to the first page when a filter changes, but respects an explicit page change', async () => {
    getMock.mockResolvedValue({ ok: true, data: page({ total: 100 }) })
    const store = useCatalogueStore()
    await store.fetchProducts()

    await store.updateQuery({ offset: 24 })
    expect(store.query.offset).toBe(24)

    await store.updateQuery({ name: 'flow' })
    expect(store.query.offset).toBe(0)
  })

  it('never filters or sorts the returned items on the client — items are exactly what the API returned', async () => {
    const apiItems = page({
      items: [
        { ...page().items[0]!, id: 'b', name: 'Zebra' },
        { ...page().items[0]!, id: 'a', name: 'Apple' },
      ],
    })
    getMock.mockResolvedValueOnce({ ok: true, data: apiItems })
    const store = useCatalogueStore()

    await store.fetchProducts()

    // Order and membership must match the API response exactly — 'Zebra' before
    // 'Apple' even though that isn't alphabetical, because sorting is the
    // server's job, not the store's.
    expect(store.items.map((item) => item.id)).toEqual(['b', 'a'])
  })

  it('surfaces a 422 for an unknown category as an error, not an empty result', async () => {
    getMock.mockResolvedValueOnce({
      ok: false,
      error: { kind: 'http', status: 422, message: "Unknown category: 'not-real'" },
    })
    const store = useCatalogueStore()

    await store.updateQuery({ category: 'not-real' })

    expect(store.error).toEqual({
      kind: 'http',
      status: 422,
      message: "Unknown category: 'not-real'",
    })
    expect(store.items).toEqual([])
    expect(store.total).toBe(0)
  })

  it('discards a superseded response so a slow earlier request cannot overwrite a newer one', async () => {
    const resolvers: ((result: ApiResult<ProductPage>) => void)[] = []
    getMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve)
        }),
    )
    const store = useCatalogueStore()

    const first = store.updateQuery({ name: 'a' })
    const second = store.updateQuery({ name: 'ab' })

    // The slow, superseded 'a' response lands after the newer 'ab' response.
    resolvers[1]!({ ok: true, data: page({ total: 2 }) })
    resolvers[0]!({ ok: true, data: page({ total: 999 }) })
    await Promise.all([first, second])

    expect(store.total).toBe(2)
  })

  it('fetches the category list without a hardcoded fallback', async () => {
    const categories: Category[] = [
      { slug: 'books', name: 'Books' },
      { slug: 'software', name: 'Software' },
    ]
    getMock.mockResolvedValueOnce({ ok: true, data: categories })
    const store = useCatalogueStore()

    await store.fetchCategories()

    expect(getMock).toHaveBeenCalledWith('/categories')
    expect(store.categories).toEqual(categories)
  })
})
