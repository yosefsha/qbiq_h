/**
 * Reads the session `SessionGuard` resolved for this request.
 *
 * Controllers take `@CurrentSession() session: SessionId` and never read the
 * cookie themselves, so session plumbing lives in exactly one place.
 */

import { ExecutionContext, InternalServerErrorException, createParamDecorator } from '@nestjs/common'

import { SESSION_REQUEST_PROPERTY, RequestWithSession } from './session.middleware'
import { SessionId } from './session-id'

export const CurrentSession = createParamDecorator(
  (_data: unknown, context: ExecutionContext): SessionId => {
    const request = context.switchToHttp().getRequest<RequestWithSession>()
    const sessionId = request[SESSION_REQUEST_PROPERTY]
    if (sessionId === undefined) {
      // Reaching this means a route asked for a session without `SessionGuard`
      // in front of it — a wiring bug, not a condition to degrade from, so it
      // fails loudly rather than quietly serving someone else's empty Cart.
      throw new InternalServerErrorException(
        'CurrentSession used on a route without SessionGuard',
      )
    }
    return sessionId
  },
)
