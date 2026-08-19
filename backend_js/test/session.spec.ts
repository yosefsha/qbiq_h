/**
 * The session cookie, on every shape of response a route can produce.
 *
 * The cookie is written by middleware rather than by the guard that resolves
 * the session, and this file is why: a 204, a hand-built response, a
 * validation failure and an unhandled exception all have to carry it. A
 * first-time Shopper whose very first Cart call fails would otherwise get no
 * cookie at all, orphaning the Redis record and losing their Cart on the next
 * request.
 */

import {
  Body,
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  Post,
  Res,
  UseGuards,
  ValidationPipe,
} from '@nestjs/common'
import { IsInt, Min } from 'class-validator'
import { Response } from 'express'
import request from 'supertest'

import { CurrentSession } from '../src/common/session/current-session.decorator'
import { SessionGuard } from '../src/common/session/session.guard'
import { SessionId } from '../src/common/session/session-id'
import { TestApp, createTestApp, sessionCookieHeader, sessionCookieValue } from './app-factory'
import { FailingRedis, FakeRedis } from './fake-redis'

class QuantityBody {
  @IsInt()
  @Min(1)
  quantity!: number
}

/** Every response shape a route can produce, each behind the session guard. */
@Controller('probe')
@UseGuards(SessionGuard)
class ProbeController {
  @Get('whoami')
  whoami(@CurrentSession() session: SessionId): { length: number } {
    return { length: session.value.length }
  }

  @Get('direct-response')
  direct(@Res() response: Response): void {
    response.status(200).json({ ok: true })
  }

  @Get('no-content')
  @HttpCode(HttpStatus.NO_CONTENT)
  noContent(): void {}

  @Post('rejects')
  rejects(
    @Body(new ValidationPipe({ errorHttpStatusCode: HttpStatus.UNPROCESSABLE_ENTITY }))
    _body: QuantityBody,
  ): { ok: boolean } {
    return { ok: true }
  }

  @Get('boom')
  boom(): never {
    throw new Error('deliberate failure')
  }
}

/** A route with no guard in front of it: it must mint nothing. */
@Controller('open')
class OpenController {
  @Get('no-session')
  noSession(): { ok: boolean } {
    return { ok: true }
  }
}

describe('session cookie', () => {
  let context: TestApp

  beforeEach(async () => {
    context = await createTestApp({ controllers: [ProbeController, OpenController] })
  })

  afterEach(async () => {
    await context.close()
  })

  const client = () => request(context.app.getHttpServer())

  it.each([
    ['GET', '/probe/whoami', 200],
    ['GET', '/probe/direct-response', 200],
    ['GET', '/probe/no-content', 204],
    ['GET', '/probe/boom', 500],
  ])('issues the cookie on a %s %s answering %p', async (_method, path, status) => {
    const response = await client().get(path)

    expect(response.status).toBe(status)
    expect(sessionCookieValue(response.headers['set-cookie'])).toHaveLength(43)
  })

  it('issues the cookie on a body that fails validation', async () => {
    const response = await client().post('/probe/rejects').send({ quantity: 0 })

    expect(response.status).toBe(422)
    expect(sessionCookieValue(response.headers['set-cookie'])).toHaveLength(43)
  })

  it('mints nothing for a route that never asked for a session', async () => {
    const response = await client().get('/open/no-session')

    expect(response.status).toBe(200)
    expect(response.headers['set-cookie']).toBeUndefined()
  })

  it('mints a token of exactly the shape it accepts back', async () => {
    const token = sessionCookieValue((await client().get('/probe/whoami')).headers['set-cookie'])

    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/)
  })

  it('mints a different token per Shopper', async () => {
    const first = sessionCookieValue((await client().get('/probe/whoami')).headers['set-cookie'])
    const second = sessionCookieValue((await client().get('/probe/whoami')).headers['set-cookie'])

    expect(first).not.toBe(second)
  })

  it.each([
    ['short', 'session_id=abc'],
    ['too long', `session_id=${'a'.repeat(44)}`],
    ['out of alphabet', `session_id=${'a'.repeat(42)}!`],
    ['empty', 'session_id='],
  ])('replaces a %s cookie rather than trusting it', async (_label, cookie) => {
    const response = await client().get('/probe/whoami').set('Cookie', cookie)

    const issued = sessionCookieValue(response.headers['set-cookie'])
    expect(issued).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(cookie).not.toContain(issued as string)
  })

  it('reuses a well-formed cookie unchanged', async () => {
    const token = 'a'.repeat(43)
    const response = await client().get('/probe/whoami').set('Cookie', `session_id=${token}`)

    expect(sessionCookieValue(response.headers['set-cookie'])).toBe(token)
  })

  it('carries the ADR-001 attributes', async () => {
    const cookie = sessionCookieHeader((await client().get('/probe/whoami')).headers['set-cookie'])

    expect(cookie).toContain('HttpOnly')
    expect(cookie).toContain('SameSite=Lax')
    expect(cookie).toContain('Path=/')
    expect(cookie).toContain('Max-Age=1800')
  })

  it('refreshes the Redis record on every request, keeping the TTL sliding', async () => {
    const redis = new FakeRedis()
    const app = await createTestApp({ controllers: [ProbeController], redis })
    try {
      const token = 'b'.repeat(43)
      await request(app.app.getHttpServer())
        .get('/probe/whoami')
        .set('Cookie', `session_id=${token}`)

      expect(redis.ttl(`session:${token}`)).toBe(1800)
      expect(redis.raw(`session:${token}`)).toBe('1')
    } finally {
      await app.close()
    }
  })

  it('still issues a cookie when the session store is unreachable', async () => {
    const app = await createTestApp({
      controllers: [ProbeController],
      redis: new FailingRedis() as unknown as FakeRedis,
    })
    try {
      const response = await request(app.app.getHttpServer()).get('/probe/whoami')

      expect(response.status).toBe(200)
      expect(sessionCookieValue(response.headers['set-cookie'])).toHaveLength(43)
    } finally {
      await app.close()
    }
  })

  it('never renders the token through toString or JSON', () => {
    const session = new SessionId('c'.repeat(43))

    expect(`${session}`).not.toContain('ccc')
    expect(JSON.stringify({ session })).not.toContain('ccc')
    // The value is still reachable deliberately — the repositories need it.
    expect(session.value).toHaveLength(43)
  })
})
