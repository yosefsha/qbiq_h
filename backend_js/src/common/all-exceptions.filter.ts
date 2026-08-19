/**
 * Turns anything thrown while handling a request into the wire error shape.
 *
 * The SPA reads `detail` off an error body and shows it (see
 * `frontend/src/api/client.ts`), which is FastAPI's shape — so this filter
 * rewrites Nest's default `{statusCode, message, error}` envelope into
 * `{detail: ...}`. Without it, every error message the storefront displays
 * would change depending on which backend answered.
 *
 * An unhandled exception becomes a 500 whose body names nothing: the message
 * and its stack go to the log, where an operator is looking anyway. This
 * mirrors `RequestIdMiddleware`'s exception branch in the Python service, and
 * it exists for the same reason — a "request started" line with no matching
 * outcome fires the 5xx alarm with nothing to diagnose it.
 */

import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpException,
  HttpStatus,
} from '@nestjs/common'
import { Request, Response } from 'express'

import { JsonLogger } from './logging/json-logger'

const logger = new JsonLogger('app.request')

/**
 * Extracts the `detail` payload from a Nest `HttpException`.
 *
 * A `ValidationPipe` failure carries an array of messages, which is passed
 * through as a list — FastAPI reports its own validation errors as a list
 * under the same key. Anything else collapses to a single string.
 */
function toDetail(exception: HttpException): unknown {
  const response = exception.getResponse()
  if (typeof response === 'string') {
    return response
  }
  const body = response as Record<string, unknown>
  if ('detail' in body) {
    return body.detail
  }
  const message = body.message
  if (Array.isArray(message)) {
    return message
  }
  return typeof message === 'string' ? message : exception.message
}

@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost): void {
    const context = host.switchToHttp()
    const response = context.getResponse<Response>()
    const request = context.getRequest<Request>()

    if (exception instanceof HttpException) {
      response.status(exception.getStatus()).json({ detail: toDetail(exception) })
      return
    }

    logger.exception('request failed', exception, {
      method: request.method,
      path: request.path,
    })
    response
      .status(HttpStatus.INTERNAL_SERVER_ERROR)
      .json({ detail: 'Internal Server Error' })
  }
}
