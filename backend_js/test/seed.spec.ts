/**
 * The seeder, against a real Postgres.
 *
 * The property that matters is idempotence: `migrate_js` runs this on every
 * `docker compose up`, so a second run must add nothing. The thumbnail
 * reconciliation is the one deliberate exception, and the test below pins down
 * both halves of it — the thumbnail is corrected, and nothing else is.
 */

import { CategoryEntity } from '../src/db/entities/category.entity'
import { PRODUCT_SEEDS, CATEGORY_SEEDS, seedCatalogue } from '../src/seed'
import { ProductEntity } from '../src/db/entities/product.entity'
import { ReviewEntity } from '../src/db/entities/review.entity'
import { describeWithPostgres, useTestDatabase } from './postgres'

const EXPECTED_REVIEWS = PRODUCT_SEEDS.reduce(
  (total, product) => total + product.reviews.length,
  0,
)

describeWithPostgres('CatalogueSeeder', () => {
  const database = useTestDatabase()

  async function counts(): Promise<{ categories: number; products: number; reviews: number }> {
    const dataSource = database.require()
    return {
      categories: await dataSource.getRepository(CategoryEntity).count(),
      products: await dataSource.getRepository(ProductEntity).count(),
      reviews: await dataSource.getRepository(ReviewEntity).count(),
    }
  }

  it('loads the whole catalogue on an empty database', async () => {
    await seedCatalogue(database.require())

    expect(await counts()).toEqual({
      categories: CATEGORY_SEEDS.length,
      products: PRODUCT_SEEDS.length,
      reviews: EXPECTED_REVIEWS,
    })
  })

  it('adds nothing on a second or third run', async () => {
    const dataSource = database.require()
    await seedCatalogue(dataSource)
    const after = await counts()

    await seedCatalogue(dataSource)
    await seedCatalogue(dataSource)

    expect(await counts()).toEqual(after)
  })

  it('reconciles a thumbnail that points at a dead URL', async () => {
    const dataSource = database.require()
    await seedCatalogue(dataSource)

    const products = dataSource.getRepository(ProductEntity)
    const seed = PRODUCT_SEEDS[0]
    const product = await products.findOneByOrFail({ name: seed.name })
    await products.update(product.id, {
      thumbnailUrl: 'https://cdn.qbiq.dev/products/dead.jpg',
    })

    await seedCatalogue(dataSource)

    const reconciled = await products.findOneByOrFail({ id: product.id })
    expect(reconciled.thumbnailUrl).toBe(seed.thumbnailUrl)
  })

  it('leaves every other edited field alone — a re-seed is not a revert', async () => {
    const dataSource = database.require()
    await seedCatalogue(dataSource)

    const products = dataSource.getRepository(ProductEntity)
    const seed = PRODUCT_SEEDS[0]
    const product = await products.findOneByOrFail({ name: seed.name })
    await products.update(product.id, {
      priceMinor: 1,
      shortDescription: 'edited in the demo',
    })

    await seedCatalogue(dataSource)

    const untouched = await products.findOneByOrFail({ id: product.id })
    expect(untouched.priceMinor).toBe(1)
    expect(untouched.shortDescription).toBe('edited in the demo')
  })

  it('adds a review that was deleted, matching on author', async () => {
    const dataSource = database.require()
    await seedCatalogue(dataSource)

    const reviews = dataSource.getRepository(ReviewEntity)
    const seeded = PRODUCT_SEEDS.find((product) => product.reviews.length > 0)
    const product = await dataSource
      .getRepository(ProductEntity)
      .findOneByOrFail({ name: (seeded as (typeof PRODUCT_SEEDS)[number]).name })
    await reviews.delete({ productId: product.id })

    await seedCatalogue(dataSource)

    expect(await reviews.countBy({ productId: product.id })).toBe(
      (seeded as (typeof PRODUCT_SEEDS)[number]).reviews.length,
    )
  })

  it('prices everything in integer minor units', async () => {
    await seedCatalogue(database.require())

    const products = await database.require().getRepository(ProductEntity).find()
    for (const product of products) {
      expect(Number.isInteger(product.priceMinor)).toBe(true)
      expect(product.priceMinor).toBeGreaterThan(0)
      expect(product.currency).toHaveLength(3)
    }
  })

  it('gives every product a category that exists', async () => {
    await seedCatalogue(database.require())

    const products = await database
      .require()
      .getRepository(ProductEntity)
      .find({ relations: { category: true } })

    expect(products).toHaveLength(PRODUCT_SEEDS.length)
    for (const product of products) {
      expect(product.category).not.toBeNull()
    }
  })
})

describe('seed data', () => {
  it('carries the same catalogue the Python seeder does', () => {
    expect(CATEGORY_SEEDS.map((category) => category.slug)).toEqual([
      'e-books',
      'software-licences',
      'online-courses',
    ])
    expect(PRODUCT_SEEDS).toHaveLength(32)
  })

  it('names a category every product can resolve', () => {
    const slugs = new Set(CATEGORY_SEEDS.map((category) => category.slug))

    for (const product of PRODUCT_SEEDS) {
      expect(slugs.has(product.categorySlug)).toBe(true)
    }
  })

  it('has a unique name per product, which is the seeder’s natural key', () => {
    const names = PRODUCT_SEEDS.map((product) => product.name)

    expect(new Set(names).size).toBe(names.length)
  })

  it('has a unique author per product’s reviews, the review natural key', () => {
    for (const product of PRODUCT_SEEDS) {
      const authors = product.reviews.map((review) => review.author)
      expect(new Set(authors).size).toBe(authors.length)
    }
  })

  it('points every thumbnail at the frontend asset path', () => {
    for (const product of PRODUCT_SEEDS) {
      expect(product.thumbnailUrl).toMatch(/^\/assets\/thumbnails\/[a-z0-9-]+\.svg$/)
    }
  })
})
