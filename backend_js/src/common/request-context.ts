/**
 * Per-request context propagation for structured logging.
 *
 * Holds the current request id in an `AsyncLocalStorage` — Node's equivalent
 * of Python's `contextvars` — so any log statement emitted while handling a
 * request, regardless of call depth, can be tagged with that request's id
 * without threading it through every function signature.
 */

import { AsyncLocalStorage } from 'node:async_hooks'
import { randomUUID } from 'node:crypto'

/** What `getRequestId()` reports outside of a request. */
export const NO_REQUEST_ID = '-'

interface RequestContext {
  readonly requestId: string
}

const storage = new AsyncLocalStorage<RequestContext>()

/** Generates a new opaque request id. */
export function generateRequestId(): string {
  return randomUUID()
}

/** Runs `callback` with `requestId` as the current request id. */
export function runWithRequestId<T>(requestId: string, callback: () => T): T {
  return storage.run({ requestId }, callback)
}

/** Returns the current request id, or `-` outside of a request context. */
export function getRequestId(): string {
  return storage.getStore()?.requestId ?? NO_REQUEST_ID
}
