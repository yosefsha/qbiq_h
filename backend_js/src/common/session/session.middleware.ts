/**
 * Writes the session cookie onto the real outgoing response.
 *
 * The cookie cannot be set from `SessionGuard` alone and be sure of landing:
 * an exception thrown after the guard runs is turned into a fresh response by
 * `AllExceptionsFilter`, and any header the guard had staged on a response it
 * never got to send would be lost. A first-time Shopper whose very first Cart
 * call 422s would then get no cookie at all, orphaning the Redis record and
 * losing their Cart on the next request.
 *
 * So the header is attached at the last possible moment, by wrapping
 * `writeHead` — the single choke point every Express response passes through,
 * whether it was sent by a controller, by the validation pipe, or by the
 * exception filter. It is the same trick Starlette's `BaseHTTPMiddleware`
 * plays with its send-wrapper on the Python side.
 *
 * Attaching it here also makes the TTL genuinely sliding: the cookie is
 * rewritten on every request that used a session, so an active Shopper's
 * browser-side expiry keeps moving. Issued only at mint time, the browser
 * would drop the cookie a fixed interval after first contact no matter how
 * recently the Shopper had clicked.
 */

import { serialize } from 'cookie'
import { NextFunction, Request, Response } from 'express'

import { settings } from '../../config/settings'
import { SESSION_COOKIE_NAME, SessionId } from './session-id'

/**
 * Request property carrying the session for this middleware to write out.
 *
 * Set only by `SessionGuard`, so a route that never asks for a session —
 * `/health`, hit continuously by the ALB, and the whole catalogue — mints no
 * session and receives no cookie.
 */
export const SESSION_REQUEST_PROPERTY = 'sessionId'

export interface RequestWithSession extends Request {
  [SESSION_REQUEST_PROPERTY]?: SessionId
}

/**
 * Serializes the session cookie per ADR-001: HttpOnly, config-driven Secure,
 * SameSite=Lax.
 *
 * `secure` is read from settings rather than hardcoded `true` — hardcoded, it
 * drops the cookie silently over the plain HTTP the local Compose stack
 * serves on.
 */
function serializeSessionCookie(sessionId: SessionId): string {
  return serialize(SESSION_COOKIE_NAME, sessionId.value, {
    maxAge: settings.sessionTtlSeconds,
    path: '/',
    secure: settings.cookieSecure,
    httpOnly: true,
    sameSite: 'lax',
  })
}

/** Appends `cookie` to any `Set-Cookie` header already staged on `response`. */
function appendSetCookie(response: Response, cookie: string): void {
  const existing = response.getHeader('Set-Cookie')
  if (existing === undefined) {
    response.setHeader('Set-Cookie', cookie)
    return
  }
  const values = Array.isArray(existing) ? existing : [String(existing)]
  response.setHeader('Set-Cookie', [...values, cookie])
}

export function sessionCookieMiddleware(
  request: RequestWithSession,
  response: Response,
  next: NextFunction,
): void {
  const originalWriteHead = response.writeHead.bind(response)

  // `res.end()` calls `writeHead` implicitly when nothing called it
  // explicitly, so this one wrapper covers every way a response can be sent —
  // including the ones this middleware never sees return.
  response.writeHead = function patchedWriteHead(
    this: Response,
    ...args: Parameters<Response['writeHead']>
  ): Response {
    const sessionId = request[SESSION_REQUEST_PROPERTY]
    if (sessionId !== undefined && !response.headersSent) {
      appendSetCookie(response, serializeSessionCookie(sessionId))
    }
    return originalWriteHead(...args) as unknown as Response
  } as Response['writeHead']

  next()
}
