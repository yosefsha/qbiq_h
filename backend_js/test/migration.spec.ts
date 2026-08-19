/**
 * The hand-written migration, against a real Postgres.
 *
 * The migration is written by hand so that it agrees with the Alembic revision
 * on the Python side, which means nothing generates it from the entities and
 * nothing keeps the two in step — except this. After the migration runs, the
 * schema builder must find no difference between the database and the
 * entities; if it finds one, either the migration or an entity has drifted.
 */

import { DataSource } from 'typeorm'

import { ENTITIES } from '../src/db/data-source-options'
import { TEST_DATABASE_URL, describeWithPostgres } from './postgres'

describeWithPostgres('InitialSchema migration', () => {
  let dataSource: DataSource

  beforeAll(async () => {
    dataSource = await new DataSource({
      type: 'postgres',
      url: TEST_DATABASE_URL,
      entities: ENTITIES,
      migrations: [`${__dirname}/../src/migrations/*.ts`],
      migrationsTableName: 'typeorm_migrations',
      synchronize: false,
      dropSchema: true,
      logging: false,
    }).initialize()
    await dataSource.runMigrations()
  })

  afterAll(async () => {
    if (dataSource?.isInitialized) {
      await dataSource.destroy()
    }
  })

  it('builds a schema the entities agree with', async () => {
    // An empty log means `synchronize` would do nothing — the migration and
    // the entity decorators describe the same schema. Foreign-key *renames*
    // are filtered out: the migration uses Postgres' default constraint names
    // so the schema matches the Alembic revision exactly, while TypeORM would
    // rather call them `FK_<hash>`. The relationship itself, including its ON
    // DELETE behaviour, is asserted below.
    const pending = await dataSource.driver.createSchemaBuilder().log()
    const substantive = pending.upQueries
      .map((query) => query.query)
      // Postgres' `<table>_<column>_fkey` on one side, TypeORM's `FK_<hash>`
      // on the other — the same constraint under two naming conventions.
      .filter((query) => !/CONSTRAINT "(?:FK_[0-9a-f]+|\w+_fkey)"/.test(query))

    expect(substantive).toEqual([])
  })

  it('names its constraints the way the Alembic revision does', async () => {
    // Primary keys, unique constraints, foreign keys and checks only.
    // Postgres 17 also records a row per NOT NULL column here, and the
    // migration ledger is TypeORM's own table, not part of the schema.
    const rows: { conname: string }[] = await dataSource.query(
      `SELECT conname FROM pg_constraint
       WHERE connamespace = 'public'::regnamespace
         AND contype IN ('p', 'u', 'f', 'c')
         AND conrelid::regclass::text <> 'typeorm_migrations'
       ORDER BY conname`,
    )

    // Postgres' defaults for the unnamed ones, Alembic's explicit names for
    // the two checks. A rename here means the two services' schemas have
    // diverged, even if both still work.
    expect(rows.map((row) => row.conname)).toEqual([
      'category_pkey',
      'category_slug_key',
      'ck_product_price_minor_non_negative',
      'ck_review_rating_range',
      'product_category_id_fkey',
      'product_pkey',
      'review_pkey',
      'review_product_id_fkey',
    ])
  })

  it('records itself so a second run is a no-op', async () => {
    const applied = await dataSource.runMigrations()

    expect(applied).toEqual([])
  })

  it.each(['category', 'product', 'review'])('creates the %s table', async (table) => {
    const rows = await dataSource.query(
      'SELECT 1 FROM information_schema.tables WHERE table_name = $1',
      [table],
    )
    expect(rows).toHaveLength(1)
  })

  it.each([
    'ix_product_category_id',
    'ix_product_name',
    'ix_review_product_id',
  ])('creates the %s index', async (index) => {
    const rows = await dataSource.query('SELECT 1 FROM pg_indexes WHERE indexname = $1', [index])
    expect(rows).toHaveLength(1)
  })

  it('refuses a negative price', async () => {
    const [category] = await dataSource.query(
      `INSERT INTO category (slug, label) VALUES ('c1', 'C1') RETURNING id`,
    )

    await expect(
      dataSource.query(
        `INSERT INTO product (name, price_minor, currency, short_description, long_description, thumbnail_url, category_id)
         VALUES ('bad', -1, 'USD', 's', 'l', 't', $1)`,
        [category.id],
      ),
    ).rejects.toThrow(/ck_product_price_minor_non_negative/)
  })

  it.each([0, 6])('refuses a rating of %p', async (rating) => {
    const [category] = await dataSource.query(
      `INSERT INTO category (slug, label) VALUES ('c${rating}', 'C') RETURNING id`,
    )
    const [product] = await dataSource.query(
      `INSERT INTO product (name, price_minor, currency, short_description, long_description, thumbnail_url, category_id)
       VALUES ('p${rating}', 100, 'USD', 's', 'l', 't', $1) RETURNING id`,
      [category.id],
    )

    await expect(
      dataSource.query(
        `INSERT INTO review (product_id, author, rating, body) VALUES ($1, 'a', $2, 'b')`,
        [product.id, rating],
      ),
    ).rejects.toThrow(/ck_review_rating_range/)
  })

  it('refuses to delete a category that still has products', async () => {
    const [category] = await dataSource.query(
      `INSERT INTO category (slug, label) VALUES ('kept', 'Kept') RETURNING id`,
    )
    await dataSource.query(
      `INSERT INTO product (name, price_minor, currency, short_description, long_description, thumbnail_url, category_id)
       VALUES ('held', 100, 'USD', 's', 'l', 't', $1)`,
      [category.id],
    )

    await expect(
      dataSource.query('DELETE FROM category WHERE id = $1', [category.id]),
    ).rejects.toThrow()
  })

  it('cascades a product delete to its reviews', async () => {
    const [category] = await dataSource.query(
      `INSERT INTO category (slug, label) VALUES ('cascade', 'Cascade') RETURNING id`,
    )
    const [product] = await dataSource.query(
      `INSERT INTO product (name, price_minor, currency, short_description, long_description, thumbnail_url, category_id)
       VALUES ('doomed', 100, 'USD', 's', 'l', 't', $1) RETURNING id`,
      [category.id],
    )
    await dataSource.query(
      `INSERT INTO review (product_id, author, rating, body) VALUES ($1, 'a', 5, 'b')`,
      [product.id],
    )

    await dataSource.query('DELETE FROM product WHERE id = $1', [product.id])

    const orphans = await dataSource.query('SELECT 1 FROM review WHERE product_id = $1', [
      product.id,
    ])
    expect(orphans).toHaveLength(0)
  })

  it('defaults created_at rather than requiring the caller to set it', async () => {
    const [category] = await dataSource.query(
      `INSERT INTO category (slug, label) VALUES ('stamped', 'Stamped') RETURNING id`,
    )
    const [product] = await dataSource.query(
      `INSERT INTO product (name, price_minor, currency, short_description, long_description, thumbnail_url, category_id)
       VALUES ('stamped', 100, 'USD', 's', 'l', 't', $1) RETURNING id`,
      [category.id],
    )
    const [review] = await dataSource.query(
      `INSERT INTO review (product_id, author, rating, body) VALUES ($1, 'a', 5, 'b') RETURNING created_at`,
      [product.id],
    )

    expect(review.created_at).toBeInstanceOf(Date)
  })

  it('rejects a duplicate category slug', async () => {
    await dataSource.query(`INSERT INTO category (slug, label) VALUES ('unique', 'One')`)

    await expect(
      dataSource.query(`INSERT INTO category (slug, label) VALUES ('unique', 'Two')`),
    ).rejects.toThrow()
  })
})
