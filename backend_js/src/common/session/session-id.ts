/**
 * The anonymous session identifier (implements ADR-001, bounded by ADR-002).
 *
 * This is a bearer secret, not a display id: whoever holds the value can act
 * as the Shopper it belongs to, so it must never be logged or exposed
 * anywhere but the `HttpOnly` cookie it travels in.
 */

import { randomBytes } from 'node:crypto'

export const SESSION_COOKIE_NAME = 'session_id'
const SESSION_KEY_PREFIX = 'session:'

/**
 * 32 random bytes in base64url are always 43 characters (ceil(32 * 8 / 6) = 43,
 * with no `=` padding) — the same shape Python's `secrets.token_urlsafe(32)`
 * produces. A cookie value outside that exact shape is not a token this
 * service could have minted, so it is treated as absent rather than trusted
 * and echoed back to Redis.
 */
const TOKEN_BYTES = 32
const TOKEN_LENGTH = 43
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/

export class SessionId {
  /**
   * `toString`/`toJSON` are overridden below so this value cannot be printed
   * by an incidental string interpolation, a logger, or an error reporter —
   * the class-level rule about not logging it is otherwise only aspirational.
   */
  constructor(readonly value: string) {}

  /** The Redis key for this session's record. */
  get redisKey(): string {
    return `${SESSION_KEY_PREFIX}${this.value}`
  }

  toString(): string {
    return 'SessionId(<redacted>)'
  }

  toJSON(): string {
    return 'SessionId(<redacted>)'
  }
}

/**
 * Generates a new opaque session token.
 *
 * Deliberately random bytes rather than a UUID: a UUID is built for
 * uniqueness and is often derived from predictable inputs (timestamps, MAC
 * addresses); this value instead has to resist *guessing*, because holding it
 * is all that is required to act as the Shopper it names.
 */
export function mintSessionId(): SessionId {
  return new SessionId(randomBytes(TOKEN_BYTES).toString('base64url'))
}

/** Returns whether `token` has the shape of a value this service mints. */
export function isWellFormed(token: string): boolean {
  return token.length === TOKEN_LENGTH && TOKEN_PATTERN.test(token)
}
