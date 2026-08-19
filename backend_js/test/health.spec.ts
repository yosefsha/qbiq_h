/**
 * The readiness latch.
 *
 * The probes are injected, so every branch here is exercised with no database
 * and no Redis anywhere near it.
 */

import { HealthCheck, Probe, STATUS_OK, STATUS_UNAVAILABLE } from '../src/health/health.service'

function probes(entries: Record<string, Probe>): Map<string, Probe> {
  return new Map(Object.entries(entries))
}

describe('HealthCheck', () => {
  it('reports ok once every probe has answered', async () => {
    const check = new HealthCheck(probes({ database: async () => 1, cache: async () => 'PONG' }))

    expect(await check.status()).toEqual({ status: STATUS_OK })
    expect(check.isReady).toBe(true)
  })

  it('reports unavailable, and stays unready, while a probe fails', async () => {
    const check = new HealthCheck(
      probes({
        database: async () => {
          throw new Error('connection refused')
        },
      }),
    )

    expect(await check.status()).toEqual({ status: STATUS_UNAVAILABLE })
    expect(check.isReady).toBe(false)
  })

  it('never names the failing dependency in the response body', async () => {
    const check = new HealthCheck(
      probes({
        cache: async () => {
          throw new Error('redis is down at cache.internal')
        },
      }),
    )

    // `/health` is reachable from the internet through the ALB; which backing
    // store an anonymous caller can see is not worth publishing.
    expect(JSON.stringify(await check.status())).not.toMatch(/redis|cache/i)
  })

  it('short-circuits on the first failure', async () => {
    let secondRan = false
    const check = new HealthCheck(
      probes({
        database: async () => {
          throw new Error('down')
        },
        cache: async () => {
          secondRan = true
          return 'PONG'
        },
      }),
    )

    await check.status()
    expect(secondRan).toBe(false)
  })

  it('stops probing once latched, so the ALB check costs nothing', async () => {
    let calls = 0
    const check = new HealthCheck(
      probes({
        database: async () => {
          calls += 1
          return 1
        },
      }),
    )

    await check.status()
    await check.status()
    await check.status()

    expect(calls).toBe(1)
  })

  it('keeps a proven task healthy through a dependency blip', async () => {
    let healthy = true
    const check = new HealthCheck(
      probes({
        cache: async () => {
          if (!healthy) {
            throw new Error('blip')
          }
          return 'PONG'
        },
      }),
    )

    expect(await check.status()).toEqual({ status: STATUS_OK })

    // The blip says nothing about whether *this task* is correctly
    // configured, and failing it would have ECS replace every task at once.
    healthy = false
    expect(await check.status()).toEqual({ status: STATUS_OK })
  })

  it('latches only after every probe has passed together', async () => {
    let cacheHealthy = false
    const check = new HealthCheck(
      probes({
        database: async () => 1,
        cache: async () => {
          if (!cacheHealthy) {
            throw new Error('not yet')
          }
          return 'PONG'
        },
      }),
    )

    expect(await check.status()).toEqual({ status: STATUS_UNAVAILABLE })
    cacheHealthy = true
    expect(await check.status()).toEqual({ status: STATUS_OK })
    expect(check.isReady).toBe(true)
  })
})
