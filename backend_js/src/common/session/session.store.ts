/**
 * Reads and writes the Redis-backed session record.
 *
 * The record carries no data beyond its own existence and TTL —
 * `session:{id}` is a marker that a session is alive, refreshed on every
 * access so an active Shopper never loses their Cart to an idle timeout. The
 * Cart itself lives beside it under `cart:{id}`.
 */

import { Inject, Injectable } from '@nestjs/common'
import type { Redis } from 'ioredis'

import { JsonLogger } from '../logging/json-logger'
import { REDIS_CLIENT } from '../../redis/redis.constants'
import { settings } from '../../config/settings'
import { SessionId } from './session-id'

const logger = new JsonLogger('app.session')

@Injectable()
export class SessionStore {
  constructor(@Inject(REDIS_CLIENT) private readonly redis: Redis) {}

  /**
   * Creates or refreshes the session record with a sliding TTL.
   *
   * A Redis outage degrades this to a logged no-op rather than a failed
   * request: cookie issuance does not depend on Redis being reachable, so
   * browsing keeps working. Whatever needs the record to actually exist — a
   * Cart write — surfaces the outage itself when it tries to read or write
   * `cart:{id}` next to it.
   */
  async touch(sessionId: SessionId): Promise<void> {
    try {
      await this.redis.set(sessionId.redisKey, '1', 'EX', settings.sessionTtlSeconds)
    } catch {
      // Deliberately logs no identifier. Every extra field here becomes a
      // top-level JSON key, so passing the Redis key would write
      // `session:{token}` — a live bearer credential — into CloudWatch on
      // every request for the duration of an outage, where 30-day retention
      // keeps it readable by anyone with log access.
      logger.error('session store unreachable; cookie issued without a Redis record')
    }
  }
}
