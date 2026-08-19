/**
 * The caching decorator: key derivation, the kind discriminator, TTLs, and
 * what happens when Redis is gone.
 *
 * The inner repository is a spy wrapping `InMemoryRepository`, so "was this a
 * hit?" is answered by counting calls that reached storage rather than by
 * reading the cache back.
 */

import { CachedProductRepository, stableHash } from '../src/repositories/cached-product.repository'
import { InMemoryRepository } from '../src/domain/fakes'
import { ProductQuery, SortDirection, SortKey, makeProductQuery } from '../src/domain/catalog'
import { ProductRepository } from '../src/domain/repositories'
import { UnknownSortKeyError } from '../src/domain/errors'
import { CATALOGUE } from './catalogue-fixtures'
import { FailingRedis, FakeRedis } from './fake-redis'

const TTL = 300

class CountingRepository implements ProductRepository {
  listProductsCalls = 0
  getProductCalls = 0
  getProductDetailCalls = 0
  listCategoriesCalls = 0

  constructor(private readonly inner: ProductRepository) {}

  async listProducts(query: ProductQuery) {
    this.listProductsCalls += 1
    return this.inner.listProducts(query)
  }

  async getProduct(productId: string) {
    this.getProductCalls += 1
    return this.inner.getProduct(productId)
  }

  async getProductDetail(productId: string) {
    this.getProductDetailCalls += 1
    return this.inner.getProductDetail(productId)
  }

  async listCategories() {
    this.listCategoriesCalls += 1
    return this.inner.listCategories()
  }
}

function build(): {
  cached: CachedProductRepository
  inner: CountingRepository
  redis: FakeRedis
} {
  const inner = new CountingRepository(new InMemoryRepository(CATALOGUE))
  const redis = new FakeRedis()
  return { cached: new CachedProductRepository(inner, redis.asRedis(), TTL), inner, redis }
}

describe('cache keys', () => {
  it('are stable for equal values regardless of how the query was built', () => {
    const left = makeProductQuery({ sort: SortKey.PRICE, limit: 5 })
    const right = makeProductQuery({ limit: 5, sort: SortKey.PRICE })

    expect(stableHash(left)).toBe(stableHash(right))
  })

  it('differ when any field differs', () => {
    const base = makeProductQuery()

    expect(stableHash(base)).not.toBe(stableHash(makeProductQuery({ offset: 1 })))
    expect(stableHash(base)).not.toBe(stableHash(makeProductQuery({ limit: 21 })))
    expect(stableHash(base)).not.toBe(
      stableHash(makeProductQuery({ direction: SortDirection.DESC })),
    )
    expect(stableHash(base)).not.toBe(stableHash(makeProductQuery({ nameContains: 'x' })))
  })
})

describe('CachedProductRepository', () => {
  it('serves a second identical listing from Redis', async () => {
    const { cached, inner } = build()

    await cached.listProducts(makeProductQuery())
    await cached.listProducts(makeProductQuery())

    expect(inner.listProductsCalls).toBe(1)
  })

  it('does not confuse two different listings', async () => {
    const { cached, inner } = build()

    await cached.listProducts(makeProductQuery())
    await cached.listProducts(makeProductQuery({ offset: 1 }))

    expect(inner.listProductsCalls).toBe(2)
  })

  it('sets the TTL on both key kinds', async () => {
    const { cached, redis } = build()

    await cached.listProducts(makeProductQuery())
    await cached.getProduct('1')

    for (const key of redis.keys()) {
      expect(redis.ttl(key)).toBe(TTL)
    }
    expect(redis.keys().some((key) => key.startsWith('products:q:'))).toBe(true)
    expect(redis.keys()).toContain('products:id:1')
  })

  it('lets a detail entry answer a summary read', async () => {
    const { cached, inner } = build()

    await cached.getProductDetail('1')
    const summary = await cached.getProduct('1')

    expect(inner.getProductCalls).toBe(0)
    expect(summary).toMatchObject({ id: '1', name: 'Deep Work' })
  })

  it('treats a summary entry as a miss for a detail read', async () => {
    const { cached, inner, redis } = build()
    // A summary payload, as a repository that only ever returns summaries
    // would have written. Without the kind discriminator this would answer the
    // detail read and serve a product page with no long description and no
    // reviews.
    redis.seed(
      'products:id:1',
      JSON.stringify({
        kind: 'product',
        id: '1',
        name: 'Deep Work',
        priceMinor: 1499,
        currency: 'USD',
        shortDescription: 'A practical guide to focus.',
        thumbnailUrl: '/assets/thumbnails/deep-work.svg',
        category: { slug: 'e-books', name: 'E-Books' },
      }),
    )

    const detail = await cached.getProductDetail('1')

    expect(inner.getProductDetailCalls).toBe(1)
    expect(detail?.longDescription).toBeDefined()
    expect(detail?.reviews).toHaveLength(1)
  })

  it('answers a summary read from that same summary entry', async () => {
    const { cached, inner, redis } = build()
    redis.seed(
      'products:id:2',
      JSON.stringify({
        kind: 'product',
        id: '2',
        name: 'Atomic Habits',
        priceMinor: 1299,
        currency: 'USD',
        shortDescription: 'Small changes, remarkable results.',
        thumbnailUrl: '/assets/thumbnails/atomic-habits.svg',
        category: { slug: 'e-books', name: 'E-Books' },
      }),
    )

    expect(await cached.getProduct('2')).toMatchObject({ id: '2', name: 'Atomic Habits' })
    expect(inner.getProductCalls).toBe(0)
  })

  it('stores a detail as a detail even when it arrived through getProduct', async () => {
    const { cached, inner, redis } = build()

    // The in-memory catalogue holds product 1 as a full detail, so a summary
    // read legitimately returns one (Liskov). Storing it as a detail is
    // strictly better than truncating it to a summary.
    await cached.getProduct('1')

    expect(JSON.parse(redis.raw('products:id:1') as string).kind).toBe('product_detail')
    expect(await cached.getProductDetail('1')).not.toBeNull()
    expect(inner.getProductDetailCalls).toBe(0)
  })

  it('does not cache an absent result', async () => {
    const { cached, inner, redis } = build()

    await cached.getProduct('404')
    await cached.getProduct('404')

    expect(inner.getProductCalls).toBe(2)
    expect(redis.keys()).toEqual([])
  })

  it('never caches the category list', async () => {
    const { cached, inner } = build()

    await cached.listCategories()
    await cached.listCategories()

    expect(inner.listCategoriesCalls).toBe(2)
  })

  it('round-trips a detail through the cache without losing a field', async () => {
    const { cached } = build()

    const fresh = await cached.getProductDetail('1')
    const hit = await cached.getProductDetail('1')

    expect(hit).toEqual(fresh)
  })

  it('discards a malformed entry instead of failing the request', async () => {
    const { cached, inner, redis } = build()
    redis.seed('products:id:1', 'not json at all')

    expect(await cached.getProduct('1')).toMatchObject({ id: '1' })
    expect(inner.getProductCalls).toBe(1)
  })

  it('degrades to the source on every read when Redis is unreachable', async () => {
    const inner = new CountingRepository(new InMemoryRepository(CATALOGUE))
    const cached = new CachedProductRepository(inner, new FailingRedis().asRedis(), TTL)

    expect((await cached.listProducts(makeProductQuery())).total).toBe(3)
    expect(await cached.getProduct('1')).not.toBeNull()
    expect(await cached.getProductDetail('1')).not.toBeNull()
    expect(await cached.listCategories()).toHaveLength(2)
  })

  it('propagates an unknown sort key uncached, so it fails every time', async () => {
    const { cached, redis } = build()
    const query = { ...makeProductQuery(), sort: 'colour' as unknown as SortKey }

    await expect(cached.listProducts(query)).rejects.toThrow(UnknownSortKeyError)
    await expect(cached.listProducts(query)).rejects.toThrow(UnknownSortKeyError)
    expect(redis.keys()).toEqual([])
  })
})
