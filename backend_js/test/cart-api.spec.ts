/**
 * The four Cart operations over the wire, and the session that owns them.
 *
 * The Cart routes are the only ones that mint a session, so this file is also
 * where the cookie's presence on each shape of response is asserted.
 */

import request from 'supertest'

import { CATALOGUE } from './catalogue-fixtures'
import { TestApp, createTestApp, sessionCookieHeader, sessionCookieValue } from './app-factory'

describe('cart API', () => {
  let context: TestApp

  beforeEach(async () => {
    context = await createTestApp({ products: CATALOGUE })
  })

  afterEach(async () => {
    await context.close()
  })

  const agent = () => request.agent(context.app.getHttpServer())

  it('serves an empty cart, in USD, to a Shopper it has never seen', async () => {
    const response = await agent().get('/api/cart')

    expect(response.status).toBe(200)
    expect(response.body).toEqual({ items: [], totalMinor: 0, currency: 'USD' })
  })

  it('issues a session cookie on the first Cart request', async () => {
    const response = await agent().get('/api/cart')

    const cookie = sessionCookieHeader(response.headers['set-cookie'])
    expect(cookie).not.toBeNull()
    expect(sessionCookieValue(response.headers['set-cookie'])).toHaveLength(43)
    expect(cookie).toContain('HttpOnly')
    expect(cookie).toContain('SameSite=Lax')
    expect(cookie).toContain('Max-Age=1800')
    // Plain HTTP locally, so a Secure cookie would be dropped silently.
    expect(cookie).not.toContain('Secure')
  })

  it('reuses the cookie it was given rather than minting a second session', async () => {
    const client = agent()
    const first = await client.get('/api/cart')
    const second = await client.get('/api/cart')

    expect(sessionCookieValue(second.headers['set-cookie'])).toBe(
      sessionCookieValue(first.headers['set-cookie']),
    )
  })

  it('replaces a malformed cookie instead of trusting it', async () => {
    const response = await request(context.app.getHttpServer())
      .get('/api/cart')
      .set('Cookie', 'session_id=not-a-real-token')

    const issued = sessionCookieValue(response.headers['set-cookie'])
    expect(issued).not.toBe('not-a-real-token')
    expect(issued).toHaveLength(43)
  })

  it('adds a line and returns the whole cart, priced from the catalogue', async () => {
    const response = await agent().post('/api/cart/items').send({ productId: '1', quantity: 2 })

    expect(response.status).toBe(200)
    expect(response.body).toEqual({
      items: [
        {
          productId: '1',
          name: 'Deep Work',
          unitPriceMinor: 1499,
          quantity: 2,
          subtotalMinor: 2998,
        },
      ],
      totalMinor: 2998,
      currency: 'USD',
    })
  })

  it('increments an existing line rather than duplicating it', async () => {
    const client = agent()
    await client.post('/api/cart/items').send({ productId: '1', quantity: 2 })
    const response = await client.post('/api/cart/items').send({ productId: '1', quantity: 3 })

    expect(response.body.items).toHaveLength(1)
    expect(response.body.items[0].quantity).toBe(5)
  })

  it('keeps carts separate per session', async () => {
    const shopper = agent()
    await shopper.post('/api/cart/items').send({ productId: '1', quantity: 1 })

    const stranger = await agent().get('/api/cart')
    expect(stranger.body.items).toEqual([])
  })

  it('sets an absolute quantity on PATCH', async () => {
    const client = agent()
    await client.post('/api/cart/items').send({ productId: '1', quantity: 5 })
    const response = await client.patch('/api/cart/items/1').send({ quantity: 2 })

    expect(response.status).toBe(200)
    expect(response.body.items[0].quantity).toBe(2)
    expect(response.body.totalMinor).toBe(2998)
  })

  it('removes a line on DELETE, returning the whole cart with 200', async () => {
    const client = agent()
    await client.post('/api/cart/items').send({ productId: '1', quantity: 1 })
    const response = await client.delete('/api/cart/items/1')

    expect(response.status).toBe(200)
    expect(response.body).toEqual({ items: [], totalMinor: 0, currency: 'USD' })
  })

  it('treats deleting an absent line as a no-op, not a 404', async () => {
    const response = await agent().delete('/api/cart/items/3')

    expect(response.status).toBe(200)
    expect(response.body.items).toEqual([])
  })

  it('404s on adding a product that does not exist', async () => {
    const response = await agent().post('/api/cart/items').send({ productId: '404', quantity: 1 })

    expect(response.status).toBe(404)
    expect(response.body.detail).toBe("Unknown product id: '404'")
  })

  const invalidBodies: [Record<string, unknown>, string][] = [
    [{ productId: '1', quantity: 0 }, 'a zero quantity'],
    [{ productId: '1', quantity: -1 }, 'a negative quantity'],
    [{ productId: '1', quantity: 1.5 }, 'a fractional quantity'],
    [{ productId: '1' }, 'a missing quantity'],
    [{ quantity: 1 }, 'a missing productId'],
  ]

  it.each(invalidBodies)('422s on POST with %j (%s)', async (body) => {
    expect((await agent().post('/api/cart/items').send(body)).status).toBe(422)
  })

  it('422s on a body carrying a price, which the client may never set', async () => {
    const response = await agent()
      .post('/api/cart/items')
      .send({ productId: '1', quantity: 1, unitPriceMinor: 1 })

    expect(response.status).toBe(422)
  })

  it('422s on PATCH to quantity 0: removal is DELETE, not a second spelling of it', async () => {
    const client = agent()
    await client.post('/api/cart/items').send({ productId: '1', quantity: 1 })

    expect((await client.patch('/api/cart/items/1').send({ quantity: 0 })).status).toBe(422)
  })

  it('issues the cookie even when the request fails validation', async () => {
    const response = await request(context.app.getHttpServer())
      .post('/api/cart/items')
      .send({ productId: '1', quantity: 0 })

    expect(response.status).toBe(422)
    expect(sessionCookieValue(response.headers['set-cookie'])).toHaveLength(43)
  })

})
