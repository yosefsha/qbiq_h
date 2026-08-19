/**
 * Application entry point.
 *
 * Middleware order matters and is stated here, outermost first:
 *
 * 1. **CORS** — outermost, so error responses produced further in still pass
 *    back out through it. The other way round, a 500 reaches the browser
 *    stripped of its CORS headers and the SPA sees an opaque network failure
 *    it cannot distinguish from an unreachable server.
 * 2. **Session cookie** — outside the request-id layer, so the cookie is
 *    attached to whatever response is eventually sent, including one produced
 *    by the exception filter. Inside it, a first-time Shopper would lose their
 *    session on any error.
 * 3. **Request id** — innermost, so every log line emitted while handling the
 *    request carries it.
 */

import 'reflect-metadata'
import { HttpStatus, ValidationPipe } from '@nestjs/common'
import { NestFactory } from '@nestjs/core'

import { AppModule } from './app.module'
import { AllExceptionsFilter } from './common/all-exceptions.filter'
import { JsonLogger } from './common/logging/json-logger'
import { REQUEST_ID_HEADER, requestIdMiddleware } from './common/request-id.middleware'
import { sessionCookieMiddleware } from './common/session/session.middleware'
import { settings } from './config/settings'

const PORT = Number.parseInt(process.env.PORT ?? '8000', 10)

const logger = new JsonLogger('app.main')

export async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, {
    logger: new JsonLogger('nest'),
    // The filter below owns every error response, so Nest's own body shape
    // never reaches a client.
    bufferLogs: false,
  })

  app.enableCors({
    origin: [...settings.allowedOrigins],
    credentials: true,
    methods: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'],
    allowedHeaders: ['*'],
    // Without this the browser hides X-Request-Id from JavaScript on any
    // cross-origin response, which defeats the point of echoing it back:
    // correlating a client-side failure with the server log that explains it.
    exposedHeaders: [REQUEST_ID_HEADER],
  })

  app.use(sessionCookieMiddleware)
  app.use(requestIdMiddleware)

  // Deliberately no `whitelist` here. An undeclared *query* parameter is
  // ignored, matching FastAPI, and an undeclared *body* field is a 422 — but
  // the global pipe runs before a parameter-level one, so whitelisting here
  // would strip the extra field before the Cart controller's stricter pipe
  // ever saw it, turning a rejected body into a silently accepted one.
  app.useGlobalPipes(
    new ValidationPipe({
      transform: true,
      errorHttpStatusCode: HttpStatus.UNPROCESSABLE_ENTITY,
    }),
  )
  app.useGlobalFilters(new AllExceptionsFilter())

  // So `onApplicationShutdown` runs and the Redis socket is closed on SIGTERM,
  // which is how ECS stops a task.
  app.enableShutdownHooks()

  await app.listen(PORT, '0.0.0.0')
  logger.log('listening', { port: PORT })
}

if (require.main === module) {
  void bootstrap()
}
