/**
 * Request id middleware.
 *
 * Assigns every incoming request a unique id (or reuses a well-formed inbound
 * `X-Request-Id` header), makes it available to structured logging via
 * `request-context.ts`, echoes it back on the response, and logs the request
 * lifecycle.
 */

import { NextFunction, Request, Response } from 'express'

import { JsonLogger } from './logging/json-logger'
import { generateRequestId, runWithRequestId } from './request-context'

const logger = new JsonLogger('app.request')

export const REQUEST_ID_HEADER = 'X-Request-Id'

/**
 * An inbound request id is client-controlled input that we copy into every log
 * line for the request and echo back in a response header. Constrain it so a
 * caller cannot inject newlines into the log stream or make each request carry
 * kilobytes of attacker-chosen text into CloudWatch.
 */
const MAX_REQUEST_ID_LENGTH = 128
const REQUEST_ID_PATTERN = new RegExp(`^[A-Za-z0-9._~-]{1,${MAX_REQUEST_ID_LENGTH}}$`)

/**
 * Returns a safe request id, preferring a well-formed inbound header.
 *
 * Exported so the rejection rules can be tested directly: an HTTP client
 * refuses to *send* some of the values worth rejecting — a header carrying a
 * newline is exactly the log-forging attempt this guards against, and Node
 * will not put one on the wire.
 */
export function resolveRequestId(request: Request): string {
  const inbound = request.headers['x-request-id']
  if (typeof inbound === 'string' && REQUEST_ID_PATTERN.test(inbound)) {
    return inbound
  }
  return generateRequestId()
}

/**
 * Plain Express middleware rather than a Nest `NestMiddleware` class: the two
 * middlewares in this service have a required order relative to each other and
 * to CORS, and `app.use()` in `main.ts` states that order in one readable
 * place — where `MiddlewareConsumer.forRoutes` would spread it across a module
 * and a route-path pattern.
 */
export function requestIdMiddleware(
  request: Request,
  response: Response,
  next: NextFunction,
): void {
  const requestId = resolveRequestId(request)

  // Set eagerly rather than on the way out: an error response is produced
  // deeper in the stack (by `AllExceptionsFilter`), and a header set here is
  // already on it. The Python service reattaches the header on both paths
  // instead; the outcome is the same.
  response.setHeader(REQUEST_ID_HEADER, requestId)

  runWithRequestId(requestId, () => {
    logger.log('request started', { method: request.method, path: request.path })
    response.on('finish', () => {
      logger.log('request completed', {
        method: request.method,
        path: request.path,
        status_code: response.statusCode,
      })
    })
    next()
  })
}
