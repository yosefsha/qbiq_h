/**
 * `GET /api/products`, `/api/products/:id` and `/api/categories` over the wire.
 *
 * Run against `InMemoryRepository`, so what is asserted here is the HTTP
 * contract — key casing, status codes, paging echo — and not any particular
 * store's behaviour.
 */

import request from 'supertest'

import { CATALOGUE } from './catalogue-fixtures'
import { TestApp, createTestApp } from './app-factory'

describe('products API', () => {
  let context: TestApp

  beforeAll(async () => {
    context = await createTestApp({ products: CATALOGUE })
  })

  afterAll(async () => {
    await context.close()
  })

  const get = (path: string) => request(context.app.getHttpServer()).get(path)

  it('serves camelCase keys and the paging state it was asked for', async () => {
    const response = await get('/api/products?limit=2&offset=1')

    expect(response.status).toBe(200)
    expect(response.body).toMatchObject({ total: 3, limit: 2, offset: 1 })
    expect(Object.keys(response.body.items[0]).sort()).toEqual([
      'category',
      'currency',
      'id',
      'name',
      'priceMinor',
      'shortDescription',
      'thumbnailUrl',
    ])
  })

  it('never leaks detail-only fields into a listing row', async () => {
    const response = await get('/api/products')

    for (const item of response.body.items) {
      expect(item).not.toHaveProperty('longDescription')
      expect(item).not.toHaveProperty('reviews')
    }
  })

  it('nests the full category on every row, so a chip needs no second request', async () => {
    const response = await get('/api/products?name=deep')

    expect(response.body.items[0].category).toEqual({ slug: 'e-books', name: 'E-Books' })
  })

  it('filters by name, case-insensitively', async () => {
    const response = await get('/api/products?name=DEEP')

    expect(response.body.items.map((item: { id: string }) => item.id)).toEqual(['1'])
    expect(response.body.total).toBe(1)
  })

  it('sorts by price descending', async () => {
    const response = await get('/api/products?sort=price&direction=desc')

    expect(response.body.items.map((item: { priceMinor: number }) => item.priceMinor)).toEqual(
      [7900, 1499, 1299],
    )
  })

  it('accepts limit=0 as a request for the total alone', async () => {
    const response = await get('/api/products?limit=0')

    expect(response.status).toBe(200)
    expect(response.body.items).toEqual([])
    expect(response.body.total).toBe(3)
  })

  it('ignores query parameters it does not know, as FastAPI does', async () => {
    const response = await get('/api/products?unexpected=1')

    expect(response.status).toBe(200)
  })

  it.each([
    ['?limit=101', 'a limit above the ceiling'],
    ['?limit=-1', 'a negative limit'],
    ['?offset=-1', 'a negative offset'],
    ['?limit=abc', 'a non-numeric limit'],
    ['?sort=colour', 'an unknown sort key'],
    ['?direction=sideways', 'an unknown direction'],
  ])('422s on %s (%s)', async (query) => {
    const response = await get(`/api/products${query}`)

    expect(response.status).toBe(422)
  })

  it('422s on an unknown category slug rather than serving an empty page', async () => {
    const response = await get('/api/products?category=nope')

    expect(response.status).toBe(422)
    expect(response.body.detail).toBe("Unknown category: 'nope'")
  })

  it('serves the detail page with its long description and reviews', async () => {
    const response = await get('/api/products/1')

    expect(response.status).toBe(200)
    expect(response.body.longDescription).toContain('focus')
    expect(response.body.reviews).toEqual([
      { id: '10', author: 'Priya N.', rating: 5, body: 'Read it twice.' },
    ])
  })

  it('404s on a non-numeric product id, rather than 422ing on the path type', async () => {
    const response = await get('/api/products/abc')

    expect(response.status).toBe(404)
    expect(response.body.detail).toBe("Product 'abc' not found")
  })

  it('404s on a numeric id that names nothing', async () => {
    expect((await get('/api/products/9999')).status).toBe(404)
  })

  it('lists categories ordered by slug', async () => {
    const response = await get('/api/categories')

    expect(response.status).toBe(200)
    expect(response.body).toEqual([
      { slug: 'e-books', name: 'E-Books' },
      { slug: 'online-courses', name: 'Online Courses' },
    ])
  })

  it('sets no session cookie: browsing the catalogue mints no Shopper', async () => {
    const response = await get('/api/products')

    expect(response.headers['set-cookie']).toBeUndefined()
  })
})
