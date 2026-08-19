/**
 * What the Cart actually stores, and what it recomputes.
 *
 * `RedisCartRepository` is the one place that decides a Cart holds nothing but
 * quantities, so this is where that is pinned down: the stored payload, the
 * sliding TTL on both reads and writes, the per-line ceiling, and what happens
 * to a line whose product has left the catalogue.
 */

import { InMemoryRepository } from '../src/domain/fakes'
import { MAX_LINE_ITEM_QUANTITY, RedisCartRepository } from '../src/repositories/redis-cart.repository'
import { UnknownProductError } from '../src/domain/errors'
import { ATOMIC_HABITS, CATALOGUE, DEEP_WORK } from './catalogue-fixtures'
import { FakeRedis } from './fake-redis'

const TTL = 1800
const SESSION = 'a-session-id'
const KEY = `cart:${SESSION}`

function build(products = CATALOGUE): {
  repository: RedisCartRepository
  redis: FakeRedis
  catalogue: InMemoryRepository
} {
  const redis = new FakeRedis()
  const catalogue = new InMemoryRepository(products)
  return {
    repository: new RedisCartRepository(redis.asRedis(), catalogue, TTL),
    redis,
    catalogue,
  }
}

describe('RedisCartRepository', () => {
  it('stores only product ids and quantities — never a name, price or currency', async () => {
    const { repository, redis } = build()
    await repository.addItem(SESSION, '1', 2)

    expect(JSON.parse(redis.raw(KEY) as string)).toEqual({ '1': 2 })
    expect(redis.raw(KEY)).not.toContain('Deep Work')
    expect(redis.raw(KEY)).not.toContain('1499')
    expect(redis.raw(KEY)).not.toContain('USD')
  })

  it('never touches Redis for a cart that was never opened', async () => {
    const { repository, redis } = build()
    const cart = await repository.getCart(SESSION)

    expect(cart.items).toEqual([])
    expect(redis.keys()).toEqual([])
  })

  it('sets a TTL on write', async () => {
    const { repository, redis } = build()
    await repository.addItem(SESSION, '1', 1)

    expect(redis.ttl(KEY)).toBe(TTL)
  })

  it('slides the TTL on a read, so browsing a Cart keeps it alive', async () => {
    const { repository, redis } = build()
    await repository.addItem(SESSION, '1', 1)
    redis.clearCommands()

    await repository.getCart(SESSION)

    expect(redis.commands).toContain(`expire ${KEY}`)
  })

  it('deletes the key once the last line is removed', async () => {
    const { repository, redis } = build()
    await repository.addItem(SESSION, '1', 1)
    await repository.removeItem(SESSION, '1')

    expect(redis.has(KEY)).toBe(false)
  })

  it('re-reads every price from the catalogue, so a price change shows immediately', async () => {
    const redis = new FakeRedis()
    const original = new InMemoryRepository(CATALOGUE)
    const before = new RedisCartRepository(redis.asRedis(), original, TTL)
    await before.addItem(SESSION, '1', 2)
    expect((await before.getCart(SESSION)).items[0].product.priceMinor).toBe(1499)

    // The same Redis, a catalogue that has since been repriced. Nothing in
    // Redis changed — the Cart is rendered from the catalogue on every read.
    const repriced = new InMemoryRepository([{ ...DEEP_WORK, priceMinor: 999 }])
    const after = new RedisCartRepository(redis.asRedis(), repriced, TTL)

    const cart = await after.getCart(SESSION)
    expect(cart.items[0].product.priceMinor).toBe(999)
  })

  it('drops a line whose product has left the catalogue, without raising', async () => {
    const redis = new FakeRedis()
    const full = new RedisCartRepository(redis.asRedis(), new InMemoryRepository(CATALOGUE), TTL)
    await full.addItem(SESSION, '1', 1)
    await full.addItem(SESSION, '2', 1)

    const reduced = new RedisCartRepository(
      redis.asRedis(),
      new InMemoryRepository([ATOMIC_HABITS]),
      TTL,
    )

    const cart = await reduced.getCart(SESSION)
    expect(cart.items.map((item) => item.product.id)).toEqual(['2'])
    // The dangling quantity stays in Redis: a read must not become a write.
    expect(JSON.parse(redis.raw(KEY) as string)).toEqual({ '1': 1, '2': 1 })
  })

  it('accumulates towards the per-line ceiling and refuses to cross it', async () => {
    const { repository } = build()
    await repository.addItem(SESSION, '1', MAX_LINE_ITEM_QUANTITY - 1)

    await expect(repository.addItem(SESSION, '1', 2)).rejects.toThrow(RangeError)
    await expect(repository.addItem(SESSION, '1', 1)).resolves.toBeDefined()
  })

  it('applies the ceiling to an absolute quantity too', async () => {
    const { repository } = build()

    await expect(
      repository.setQuantity(SESSION, '1', MAX_LINE_ITEM_QUANTITY + 1),
    ).rejects.toThrow(RangeError)
  })

  it('refuses an unknown product on add, but not on removal', async () => {
    const { repository } = build()

    await expect(repository.addItem(SESSION, '404', 1)).rejects.toThrow(UnknownProductError)
    await expect(repository.removeItem(SESSION, '404')).resolves.toBeDefined()
  })

  it('removes the line when set to zero, without consulting the catalogue', async () => {
    const { repository } = build()
    await repository.addItem(SESSION, '1', 3)

    const cart = await repository.setQuantity(SESSION, '1', 0)
    expect(cart.items).toEqual([])
  })

  it('keeps one session out of another session’s Cart', async () => {
    const { repository } = build()
    await repository.addItem('shopper-a', '1', 1)

    expect((await repository.getCart('shopper-b')).items).toEqual([])
  })
})
