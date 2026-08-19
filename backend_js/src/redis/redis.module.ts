/**
 * The process-wide Redis client.
 *
 * One `ioredis` instance, built from `REDIS_URL` and shared by everything that
 * touches Redis — the session record, the Cart, and the product-query cache —
 * so its connection pool and configuration stay in exactly one place. The
 * Python service needs two clients (a sync one and an async one) because its
 * repository Protocols are synchronous; nothing here has that problem.
 *
 * Global so the cart, catalogue and health modules can inject the token
 * without each re-importing this module.
 */

import { Global, Inject, Module, OnApplicationShutdown } from '@nestjs/common'
import Redis from 'ioredis'

import { JsonLogger } from '../common/logging/json-logger'
import { settings } from '../config/settings'
import { REDIS_CLIENT } from './redis.constants'

const logger = new JsonLogger('app.redis')

/**
 * A blackholed connection (host unreachable but not immediately refused, e.g.
 * a security-group drop) hangs forever without an explicit timeout, pinning
 * whichever request made the call. A few seconds is generous for a same-VPC
 * ElastiCache round trip and short enough that an outage surfaces as a fast
 * error instead of a stuck request.
 */
const CONNECT_TIMEOUT_MS = 3_000
const COMMAND_TIMEOUT_MS = 3_000

/** Builds the client used in production and in the integration tests. */
export function createRedisClient(url: string = settings.redisUrl): Redis {
  const client = new Redis(url, {
    connectTimeout: CONNECT_TIMEOUT_MS,
    commandTimeout: COMMAND_TIMEOUT_MS,
    // Fail a command rather than queue it forever while the node is down.
    // Every caller already treats a Redis error as a degraded read (the
    // cache), a logged no-op (the session record), or a 500 (the Cart) —
    // none of them want an unbounded wait instead.
    maxRetriesPerRequest: 1,
    enableOfflineQueue: false,
  })

  // An 'error' event with no listener is an unhandled error in Node and takes
  // the process down. The callers each log their own, more useful line and
  // carry on, so this listener exists purely to keep a transient connection
  // error from being fatal.
  client.on('error', (cause: Error) => {
    logger.warn('redis connection error', { error: cause.message })
  })

  return client
}

@Global()
@Module({
  providers: [{ provide: REDIS_CLIENT, useFactory: () => createRedisClient() }],
  exports: [REDIS_CLIENT],
})
export class RedisModule implements OnApplicationShutdown {
  constructor(@Inject(REDIS_CLIENT) private readonly redis: Redis) {}

  /** Closes the socket so `app.close()` (and the test suite) can exit. */
  async onApplicationShutdown(): Promise<void> {
    await this.redis.quit().catch(() => this.redis.disconnect())
  }
}
