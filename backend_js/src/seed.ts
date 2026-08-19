/**
 * Seeds the catalogue with a realistic set of digital products.
 *
 * Run with `node dist/seed.js`. Idempotent: rerunning it never creates
 * duplicate categories, products, or reviews — each entity is looked up by its
 * natural key (category `slug`, product `name`, review `(product, author)`)
 * before being inserted, and only missing rows are added.
 *
 * The catalogue itself lives in `seed-data.json`, extracted verbatim from
 * `backend/app/seed.py` rather than retyped, so the two services seed
 * byte-identical copy and a response diff between them shows only real
 * differences.
 */

import 'reflect-metadata'
import { DataSource, EntityManager } from 'typeorm'

import { CategoryEntity } from './db/entities/category.entity'
import { ProductEntity } from './db/entities/product.entity'
import { ReviewEntity } from './db/entities/review.entity'
import { JsonLogger } from './common/logging/json-logger'
import { dataSourceOptions } from './db/data-source-options'
import seedData from './seed-data.json'

const logger = new JsonLogger('app.seed')

export interface ReviewSeed {
  author: string
  rating: number
  body: string
}

export interface ProductSeed {
  name: string
  priceMinor: number
  currency: string
  shortDescription: string
  longDescription: string
  thumbnailUrl: string
  categorySlug: string
  reviews: ReviewSeed[]
}

export interface CategorySeed {
  slug: string
  label: string
}

export const CATEGORY_SEEDS: readonly CategorySeed[] = seedData.categories
export const PRODUCT_SEEDS: readonly ProductSeed[] = seedData.products

/** Idempotently loads `CATEGORY_SEEDS` and `PRODUCT_SEEDS` into Postgres. */
export class CatalogueSeeder {
  constructor(private readonly manager: EntityManager) {}

  /** Seeds categories, then products, then reviews. */
  async run(): Promise<void> {
    const categoriesBySlug = await this.seedCategories()
    await this.seedProducts(categoriesBySlug)
  }

  /** Inserts any category from `CATEGORY_SEEDS` missing by `slug`. */
  private async seedCategories(): Promise<Map<string, CategoryEntity>> {
    const repository = this.manager.getRepository(CategoryEntity)
    const existing = new Map(
      (await repository.find()).map((category) => [category.slug, category]),
    )

    for (const seed of CATEGORY_SEEDS) {
      if (existing.has(seed.slug)) {
        continue
      }
      const category = repository.create({ slug: seed.slug, label: seed.label })
      existing.set(seed.slug, await repository.save(category))
    }
    return existing
  }

  /**
   * Inserts any product from `PRODUCT_SEEDS` missing by `name`, along with any
   * of its reviews missing by `(product, author)`, and reconciles
   * `thumbnailUrl` on products that already exist.
   */
  private async seedProducts(
    categoriesBySlug: Map<string, CategoryEntity>,
  ): Promise<void> {
    const products = this.manager.getRepository(ProductEntity)
    const reviews = this.manager.getRepository(ReviewEntity)
    const existing = new Map(
      (await products.find({ relations: { reviews: true } })).map((product) => [
        product.name,
        product,
      ]),
    )

    for (const seed of PRODUCT_SEEDS) {
      let product = existing.get(seed.name)

      if (product === undefined) {
        const category = categoriesBySlug.get(seed.categorySlug)
        if (category === undefined) {
          throw new Error(
            `Product ${seed.name} names category ${seed.categorySlug}, which is not seeded.`,
          )
        }
        product = await products.save(
          products.create({
            name: seed.name,
            priceMinor: seed.priceMinor,
            currency: seed.currency,
            shortDescription: seed.shortDescription,
            longDescription: seed.longDescription,
            thumbnailUrl: seed.thumbnailUrl,
            categoryId: category.id,
          }),
        )
        product.reviews = []
        existing.set(seed.name, product)
      } else if (product.thumbnailUrl !== seed.thumbnailUrl) {
        // Insert-only was not enough. Every seeded product once pointed at a
        // CDN host that does not exist, so a database seeded before that was
        // fixed holds dead URLs, and a re-seed that only inserts leaves every
        // one of them in place — it looks like it worked on a fresh database
        // while doing nothing to the environment that has the problem.
        //
        // Only `thumbnailUrl` is reconciled, deliberately. Prices,
        // descriptions and reviews are things a demo may have edited in place,
        // and a seed run is not a mandate to revert them; the thumbnail is the
        // one field whose seeded value is authoritative because it names a
        // file this repository ships.
        product.thumbnailUrl = seed.thumbnailUrl
        await products.save(product)
      }

      const existingAuthors = new Set((product.reviews ?? []).map((r) => r.author))
      const missing = seed.reviews.filter((review) => !existingAuthors.has(review.author))
      if (missing.length > 0) {
        await reviews.save(
          missing.map((review) =>
            reviews.create({
              productId: (product as ProductEntity).id,
              author: review.author,
              rating: review.rating,
              body: review.body,
            }),
          ),
        )
      }
    }
  }
}

/** Runs `CatalogueSeeder` in a single transaction against `dataSource`. */
export async function seedCatalogue(dataSource: DataSource): Promise<void> {
  await dataSource.transaction(async (manager) => {
    await new CatalogueSeeder(manager).run()
  })
}

async function main(): Promise<void> {
  const dataSource = new DataSource(dataSourceOptions())
  await dataSource.initialize()
  try {
    await seedCatalogue(dataSource)
    logger.log('catalogue seeded', {
      categories: CATEGORY_SEEDS.length,
      products: PRODUCT_SEEDS.length,
    })
  } finally {
    await dataSource.destroy()
  }
}

if (require.main === module) {
  main().catch((cause: unknown) => {
    logger.exception('failed to seed the catalogue', cause)
    process.exitCode = 1
  })
}
