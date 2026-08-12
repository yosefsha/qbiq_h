import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, joinUrl } from './client'

describe('joinUrl', () => {
  it('joins a base and a path without a double slash', () => {
    expect(joinUrl('/api', '/products')).toBe('/api/products')
  })

  it('tolerates a base with a trailing slash', () => {
    expect(joinUrl('/api/', '/products')).toBe('/api/products')
  })

  it('tolerates a path without a leading slash', () => {
    expect(joinUrl('/api', 'products')).toBe('/api/products')
  })
})

describe('apiClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends credentials and normalises a successful JSON response', async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: '1', name: 'Widget' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.get<{ id: string; name: string }>('/products/1')

    expect(result).toEqual({ ok: true, data: { id: '1', name: 'Widget' } })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/products/1')
    expect(init).toMatchObject({ credentials: 'include' })
  })

  it('normalises a non-2xx HTTP response into a typed http error', async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ detail: 'Product not found' }), {
          status: 404,
          statusText: 'Not Found',
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.get('/products/missing')

    expect(result).toEqual({
      ok: false,
      error: { kind: 'http', status: 404, message: 'Product not found' },
    })
  })

  it('falls back to the status text when an error body is not JSON', async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response('internal error', { status: 500, statusText: 'Internal Server Error' }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.get('/products')

    expect(result).toEqual({
      ok: false,
      error: { kind: 'http', status: 500, message: 'Internal Server Error' },
    })
  })

  it('normalises a rejected fetch (offline/DNS/CORS) into a typed network error', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.get('/products')

    expect(result).toEqual({
      ok: false,
      error: { kind: 'network', message: 'Failed to fetch' },
    })
  })

  it('sends a JSON body and Content-Type on post', async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: '1' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await apiClient.post('/cart/line-items', { productId: 'abc', quantity: 2 })

    const [, init] = fetchMock.mock.calls[0]!
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ productId: 'abc', quantity: 2 }),
      credentials: 'include',
    })
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('treats an empty successful body (e.g. 204 No Content) as no data rather than a parse error', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiClient.delete('/cart/line-items/abc')

    expect(result).toEqual({ ok: true, data: undefined })
  })
})
