/**
 * What a client sees when something goes wrong.
 *
 * Two things must survive an unhandled exception: the CORS headers, without
 * which the SPA sees an opaque network failure it cannot tell from an
 * unreachable server, and the request id, which is the only thing linking the
 * failure the Shopper saw to the log line that explains it.
 */

import { Controller, Get } from '@nestjs/common'
import request from 'supertest'

import { REQUEST_ID_HEADER, resolveRequestId } from '../src/common/request-id.middleware'
import type { Request } from 'express'
import { TestApp, createTestApp } from './app-factory'
import { CATALOGUE } from './catalogue-fixtures'

const ORIGIN = 'http://localhost:5173'

@Controller('boom')
class BoomController {
  @Get()
  boom(): never {
    throw new Error('something specific and internal: db password is hunter2')
  }
}

describe('error handling', () => {
  let context: TestApp

  beforeEach(async () => {
    context = await createTestApp({ products: CATALOGUE, controllers: [BoomController] })
  })

  afterEach(async () => {
    await context.close()
  })

  const client = () => request(context.app.getHttpServer())

  it('turns an unhandled exception into a 500 that names nothing internal', async () => {
    const response = await client().get('/boom')

    expect(response.status).toBe(500)
    expect(response.body).toEqual({ detail: 'Internal Server Error' })
    expect(JSON.stringify(response.body)).not.toContain('hunter2')
  })

  it('keeps the CORS headers on a 500', async () => {
    const response = await client().get('/boom').set('Origin', ORIGIN)

    expect(response.headers['access-control-allow-origin']).toBe(ORIGIN)
    expect(response.headers['access-control-allow-credentials']).toBe('true')
  })

  it('exposes the request id cross-origin, so the SPA can report it', async () => {
    const response = await client().get('/api/products').set('Origin', ORIGIN)

    expect(response.headers['access-control-expose-headers']).toContain(REQUEST_ID_HEADER)
  })

  it('never answers with a wildcard origin, which credentialed CORS forbids', async () => {
    const response = await client().get('/api/products').set('Origin', ORIGIN)

    expect(response.headers['access-control-allow-origin']).not.toBe('*')
  })

  it('carries a request id on a 500 as well as on a success', async () => {
    expect((await client().get('/boom')).headers['x-request-id']).toBeDefined()
    expect((await client().get('/api/products')).headers['x-request-id']).toBeDefined()
  })

  it('reuses a well-formed inbound request id', async () => {
    const response = await client().get('/api/products').set(REQUEST_ID_HEADER, 'abc-123_~.')

    expect(response.headers['x-request-id']).toBe('abc-123_~.')
  })

  it.each([
    ['a space', 'abc def'],
    ['an empty value', ''],
  ])('replaces an inbound request id containing %s', async (_label, inbound) => {
    const response = await client().get('/api/products').set(REQUEST_ID_HEADER, inbound)

    expect(response.headers['x-request-id']).not.toBe(inbound)
    expect(response.headers['x-request-id']).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('reports a 404 in the shape the SPA reads', async () => {
    const response = await client().get('/api/products/abc')

    // `frontend/src/api/client.ts` shows `detail` when it is a string.
    expect(typeof response.body.detail).toBe('string')
  })

  it('reports a validation failure under the same key', async () => {
    const response = await client().get('/api/products?limit=101')

    expect(response.status).toBe(422)
    expect(response.body).toHaveProperty('detail')
  })

  // Tested directly rather than over HTTP: Node's client refuses to put a
  // header containing a newline on the wire at all, which is precisely the
  // log-forging attempt the rule exists to reject.
  describe('resolveRequestId', () => {
    const withHeader = (value: string) =>
      resolveRequestId({ headers: { 'x-request-id': value } } as unknown as Request)

    it.each([
      ['a newline, which would forge a log line', 'abc\ndef'],
      ['a carriage return', 'abc\rdef'],
      ['an over-long value', 'a'.repeat(129)],
      ['a slash', 'abc/def'],
      ['an empty value', ''],
    ])('replaces an inbound id containing %s', (_label, inbound) => {
      expect(withHeader(inbound)).not.toBe(inbound)
      expect(withHeader(inbound)).toMatch(/^[0-9a-f-]{36}$/)
    })

    it.each(['abc-123_~.', 'a', 'a'.repeat(128)])('keeps %p', (inbound) => {
      expect(withHeader(inbound)).toBe(inbound)
    })

    it('mints one when the header is absent', () => {
      expect(resolveRequestId({ headers: {} } as unknown as Request)).toMatch(/^[0-9a-f-]{36}$/)
    })
  })
})
