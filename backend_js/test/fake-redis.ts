/**
 * An in-process stand-in for the small slice of Redis this service uses.
 *
 * `get`, `set ... EX`, `expire`, `del` and `ping` are the whole surface — the
 * session record, the Cart and the product cache use nothing else — so a fake
 * is cheaper and far more controllable than a container, and it lets the TTL
 * assertions read the expiry directly instead of sleeping.
 *
 * `FailingRedis` is the same surface with every command rejecting, which is
 * how the cache's degrade-to-a-miss behaviour and the session store's
 * degrade-to-a-log behaviour are exercised without unplugging anything.
 */

import type { Redis } from 'ioredis'

interface Entry {
  value: string
  ttlSeconds: number | null
}

export class FakeRedis {
  private readonly entries = new Map<string, Entry>()

  /** Commands recorded in order, for asserting what was actually issued. */
  readonly commands: string[] = []

  async get(key: string): Promise<string | null> {
    this.commands.push(`get ${key}`)
    return this.entries.get(key)?.value ?? null
  }

  async set(key: string, value: string, mode?: string, ttl?: number): Promise<'OK'> {
    this.commands.push(`set ${key}`)
    this.entries.set(key, {
      value,
      ttlSeconds: mode?.toUpperCase() === 'EX' && ttl !== undefined ? ttl : null,
    })
    return 'OK'
  }

  async expire(key: string, ttlSeconds: number): Promise<number> {
    this.commands.push(`expire ${key}`)
    const entry = this.entries.get(key)
    if (entry === undefined) {
      return 0
    }
    entry.ttlSeconds = ttlSeconds
    return 1
  }

  async del(key: string): Promise<number> {
    this.commands.push(`del ${key}`)
    return this.entries.delete(key) ? 1 : 0
  }

  async ping(): Promise<'PONG'> {
    this.commands.push('ping')
    return 'PONG'
  }

  // -- inspection, for assertions -------------------------------------

  has(key: string): boolean {
    return this.entries.has(key)
  }

  raw(key: string): string | undefined {
    return this.entries.get(key)?.value
  }

  ttl(key: string): number | null | undefined {
    return this.entries.get(key)?.ttlSeconds
  }

  keys(): string[] {
    return [...this.entries.keys()]
  }

  seed(key: string, value: string, ttlSeconds: number | null = null): void {
    this.entries.set(key, { value, ttlSeconds })
  }

  /** Erases the command log without touching stored data. */
  clearCommands(): void {
    this.commands.length = 0
  }

  asRedis(): Redis {
    return this as unknown as Redis
  }
}

/** Every command rejects, as an unreachable node's would. */
export class FailingRedis {
  private fail(): never {
    throw new Error('connection refused')
  }

  async get(): Promise<never> {
    return this.fail()
  }

  async set(): Promise<never> {
    return this.fail()
  }

  async expire(): Promise<never> {
    return this.fail()
  }

  async del(): Promise<never> {
    return this.fail()
  }

  async ping(): Promise<never> {
    return this.fail()
  }

  asRedis(): Redis {
    return this as unknown as Redis
  }
}
