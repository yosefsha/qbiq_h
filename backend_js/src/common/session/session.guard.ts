/**
 * Identifies the anonymous Shopper making the request.
 *
 * Applied to the Cart routes and nowhere else, which is what keeps `/health`
 * and the catalogue from minting sessions they have no use for. Reuses the
 * `session_id` cookie when present and well-formed; otherwise mints a new
 * opaque token. Every call refreshes the sliding TTL on the Redis-backed
 * session record.
 *
 * A guard rather than a parameter decorator because resolving a session is
 * asynchronous (it touches Redis) and because it must run before body
 * validation — a first-time Shopper whose first Cart call fails validation
 * still gets a cookie, matching the Python service.
 *
 * There is deliberately no header or query-parameter fallback: ADR-001
 * rejects that outright, since it would let any caller read or mutate another
 * Shopper's Cart by guessing or copying an id.
 */

import { CanActivate, ExecutionContext, Injectable } from '@nestjs/common'

import { SESSION_REQUEST_PROPERTY, RequestWithSession } from './session.middleware'
import { SESSION_COOKIE_NAME, SessionId, isWellFormed, mintSessionId } from './session-id'
import { SessionStore } from './session.store'

/** Returns the inbound session id, if the cookie is present and well-formed. */
function readSessionCookie(request: RequestWithSession): SessionId | null {
  const token = parseCookies(request.headers.cookie)[SESSION_COOKIE_NAME]
  if (token !== undefined && isWellFormed(token)) {
    return new SessionId(token)
  }
  return null
}

/**
 * Parses a `Cookie` header into a plain map.
 *
 * Hand-rolled rather than pulled in as `cookie-parser` middleware: this is the
 * only reader of cookies in the service, and a session token must not be
 * decoded — `decodeURIComponent` would turn a `%2F` in a hostile cookie into a
 * character the shape check has already ruled out.
 */
function parseCookies(header: string | undefined): Record<string, string> {
  const cookies: Record<string, string> = {}
  if (header === undefined) {
    return cookies
  }
  for (const pair of header.split(';')) {
    const separator = pair.indexOf('=')
    if (separator === -1) {
      continue
    }
    const name = pair.slice(0, separator).trim()
    if (name !== '' && !(name in cookies)) {
      cookies[name] = pair.slice(separator + 1).trim()
    }
  }
  return cookies
}

@Injectable()
export class SessionGuard implements CanActivate {
  constructor(private readonly store: SessionStore) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<RequestWithSession>()

    const sessionId = readSessionCookie(request) ?? mintSessionId()
    request[SESSION_REQUEST_PROPERTY] = sessionId
    await this.store.touch(sessionId)

    return true
  }
}
