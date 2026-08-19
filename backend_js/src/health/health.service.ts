/**
 * Health check business logic.
 *
 * `GET /health` is the ALB target group's health check, and ECS replaces any
 * task the target group calls unhealthy. That gives the check two jobs that
 * pull in opposite directions:
 *
 * - It has to be able to fail. A check that returns 200 without ever touching
 *   Postgres or Redis cannot tell a working task from one that was handed the
 *   wrong connection details — the task boots, answers 200, joins the target
 *   group, and returns 500 to every real request. A green health check that
 *   means nothing is worse than a red one.
 * - It must not amplify an outage. If every task probed its dependencies on
 *   every check, a ten-second Redis blip would fail every task at once, ECS
 *   would replace all of them, and the service would still be cycling long
 *   after the blip was over.
 *
 * The resolution is a **latch**: the dependencies are probed until they answer
 * once, and from then on the check is a constant-time read of a boolean.
 *
 * That distinguishes exactly the failure that matters. A misconfigured task
 * never latches, never becomes healthy, and the deployment circuit breaker
 * rolls the release back with the reason in the log. A task that has already
 * proven its configuration keeps passing through a dependency blip, because
 * the blip says nothing about whether *that task* is correctly configured —
 * and the requests that actually need the dependency fail loudly on their own
 * account while it lasts.
 *
 * The probes are injected rather than reached for, so the branch logic here is
 * tested without a database or a Redis anywhere near it.
 */

import { Inject, Injectable } from '@nestjs/common'
import type { Redis } from 'ioredis'
import { DataSource } from 'typeorm'

import { JsonLogger } from '../common/logging/json-logger'
import { REDIS_CLIENT } from '../redis/redis.constants'

const logger = new JsonLogger('app.health')

/**
 * Body of a passing check. Kept as a constant because the ALB matches on the
 * status code, but the tests and the runbook match on this string.
 */
export const STATUS_OK = 'ok'

/**
 * Body of a failing check. The response deliberately does not name the
 * dependency that failed: `/health` is reachable from the internet through the
 * ALB, and which of two backing stores an anonymous caller can see is not
 * something worth publishing. The name and the error go to the log, which is
 * where an operator is looking anyway.
 */
export const STATUS_UNAVAILABLE = 'unavailable'

/** A probe rejects to signal failure and resolves with anything to succeed. */
export type Probe = () => Promise<unknown>

export interface HealthReport {
  status: string
}

/** Reports whether the service is up and able to serve requests. */
export class HealthCheck {
  private ready = false

  constructor(private readonly probes: ReadonlyMap<string, Probe>) {}

  /** True once every probe has succeeded at least once. */
  get isReady(): boolean {
    return this.ready
  }

  /**
   * Returns the current health status.
   *
   * Once latched this performs no I/O at all, so the ALB's every-30s check
   * against every task costs nothing.
   */
  async status(): Promise<HealthReport> {
    if (this.ready) {
      return { status: STATUS_OK }
    }

    for (const [name, probe] of this.probes) {
      try {
        await probe()
      } catch (cause) {
        // Never fatal: the useful outcome is a 503 plus a log line naming the
        // dependency, not a 500 with a stack the ALB discards.
        logger.exception('health check dependency unavailable', cause, {
          dependency: name,
        })
        return { status: STATUS_UNAVAILABLE }
      }
    }

    this.ready = true
    logger.log('health check dependencies reachable; task is ready')
    return { status: STATUS_OK }
  }
}

/**
 * The `HealthCheck` the application serves `/health` from.
 *
 * Both stores are checked because both are required to serve a request:
 * Postgres holds the catalogue and Redis holds Sessions and Carts, which
 * ADR-003 treats as state rather than cache. A task that can reach only one of
 * them is misconfigured, not degraded.
 */
@Injectable()
export class HealthService {
  private readonly check: HealthCheck

  constructor(
    private readonly dataSource: DataSource,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
  ) {
    this.check = new HealthCheck(
      new Map<string, Probe>([
        ['database', () => this.dataSource.query('SELECT 1')],
        ['cache', () => this.redis.ping()],
      ]),
    )
  }

  async status(): Promise<HealthReport> {
    return this.check.status()
  }
}
