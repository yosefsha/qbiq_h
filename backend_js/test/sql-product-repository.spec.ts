/**
 * The Postgres-backed repository, against a real Postgres.
 *
 * These are integration tests deliberately: what is asserted here — the
 * `ILIKE` escaping, the deterministic tie ordering, the int4 range guard, the
 * `label` -> `name` mapping — is precisely the part an in-memory fake cannot
 * tell you anything about.
 */

import { DataSource } from 'typeorm'

import { CategoryEntity } from '../src/db/entities/category.entity'
import { ProductEntity } from '../src/db/entities/product.entity'
import { ReviewEntity } from '../src/db/entities/review.entity'
import { SortDirection, SortKey, makeProductQuery } from '../src/domain/catalog'
import { SqlProductRepository, escapeLike, parseProductId } from '../src/repositories/sql-product.repository'
import { UnknownSortKeyError } from '../src/domain/errors'
import { describeWithPostgres, useTestDatabase } from './postgres'

describe('parseProductId', () => {
  it.each(['1', '42', '-7', ' 8 '])('parses %p', (value) => {
    expect(parseProductId(value)).toBe(Number(value.trim()))
  })

  it.each(['abc', '', '1.5', '1e3', 'NaN', '0x10', "1; DROP TABLE product"])(
    'refuses %p before it can reach the driver',
    (value) => {
      expect(parseProductId(value)).toBeNull()
    },
  )

  it.each(['2147483648', '-2147483649', '99999999999999999999'])(
    'refuses %p as outside int4 range',
    (value) => {
      expect(parseProductId(value)).toBeNull()
    },
  )

  it('accepts the int4 bounds themselves', () => {
    expect(parseProductId('2147483647')).toBe(2147483647)
    expect(parseProductId('-2147483648')).toBe(-2147483648)
  })
})

describe('escapeLike', () => {
  it('escapes the backslash first, so it cannot double-escape a wildcard', () => {
    expect(escapeLike('a\\%b')).toBe('a\\\\\\%b')
  })

  it.each([
    ['50% off', '50\\% off'],
    ['snake_case', 'snake\\_case'],
  ])('renders %p literally', (input, expected) => {
    expect(escapeLike(input)).toBe(expected)
  })
})

describeWithPostgres('SqlProductRepository', () => {
  const database = useTestDatabase()

  async function seed(dataSource: DataSource): Promise<void> {
    const categories = dataSource.getRepository(CategoryEntity)
    const products = dataSource.getRepository(ProductEntity)
    const reviews = dataSource.getRepository(ReviewEntity)

    // TRUNCATE rather than a repository delete: an empty `where` is rejected
    // as ambiguous, and this also resets the sequences, so the primary-key
    // ordering assertions below start from a known point on every run.
    await dataSource.query('TRUNCATE review, product, category RESTART IDENTITY CASCADE')

    const ebooks = await categories.save(categories.create({ slug: 'e-books', label: 'E-Books' }))
    const courses = await categories.save(
      categories.create({ slug: 'online-courses', label: 'Online Courses' }),
    )

    const rows = [
      { name: 'Deep Work', priceMinor: 1499, categoryId: ebooks.id },
      // Two rows share a name, which is what makes the tie-break assertion
      // meaningful — `name` is deliberately not unique in the schema.
      { name: 'Duplicate', priceMinor: 500, categoryId: ebooks.id },
      { name: 'Duplicate', priceMinor: 500, categoryId: ebooks.id },
      { name: '50% off bundle', priceMinor: 100, categoryId: courses.id },
      { name: 'snake_case guide', priceMinor: 200, categoryId: courses.id },
    ]

    for (const row of rows) {
      const saved = await products.save(
        products.create({
          ...row,
          currency: 'USD',
          shortDescription: 'short',
          longDescription: 'long',
          thumbnailUrl: `/assets/thumbnails/${row.name}.svg`,
        }),
      )
      if (row.name === 'Deep Work') {
        await reviews.save([
          reviews.create({ productId: saved.id, author: 'Priya N.', rating: 5, body: 'Great.' }),
          reviews.create({ productId: saved.id, author: 'Marcus T.', rating: 4, body: 'Dense.' }),
        ])
      }
    }
  }

  const build = async (): Promise<SqlProductRepository> => {
    const dataSource = database.require()
    await seed(dataSource)
    return new SqlProductRepository(dataSource)
  }

  it('maps the category label column onto the domain name field', async () => {
    const repository = await build()

    expect(await repository.listCategories()).toEqual([
      { slug: 'e-books', name: 'E-Books' },
      { slug: 'online-courses', name: 'Online Courses' },
    ])
  })

  it('returns string ids, though the primary keys are integers', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery())
    expect(typeof page.items[0].id).toBe('string')
  })

  it('matches a name substring case-insensitively', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery({ nameContains: 'deep WORK' }))
    expect(page.items.map((item) => item.name)).toEqual(['Deep Work'])
  })

  it('treats % in the search term as a literal, not a wildcard', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery({ nameContains: '50%' }))
    expect(page.items.map((item) => item.name)).toEqual(['50% off bundle'])
  })

  it('treats _ in the search term as a literal, not a single-character wildcard', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery({ nameContains: 'snake_case' }))
    expect(page.items.map((item) => item.name)).toEqual(['snake_case guide'])

    // The wildcard reading would also match "snakeXcase", so a term that only
    // differs in the escaped character must find nothing.
    const wildcard = await repository.listProducts(makeProductQuery({ nameContains: 'snake_c' }))
    expect(wildcard.total).toBe(1)
  })

  it('orders ties by primary key, so paging cannot drop or repeat a row', async () => {
    const repository = await build()

    const query = { nameContains: 'Duplicate', sort: SortKey.NAME, limit: 1 }
    const first = await repository.listProducts(makeProductQuery({ ...query, offset: 0 }))
    const second = await repository.listProducts(makeProductQuery({ ...query, offset: 1 }))

    expect(first.total).toBe(2)
    expect(first.items[0].id).not.toBe(second.items[0].id)
    expect(Number(first.items[0].id)).toBeLessThan(Number(second.items[0].id))
  })

  it('sorts by price in both directions', async () => {
    const repository = await build()

    const ascending = await repository.listProducts(makeProductQuery({ sort: SortKey.PRICE }))
    const descending = await repository.listProducts(
      makeProductQuery({ sort: SortKey.PRICE, direction: SortDirection.DESC }),
    )

    expect(ascending.items[0].priceMinor).toBe(100)
    expect(descending.items[0].priceMinor).toBe(1499)
  })

  it('reports the total for the filtered set, not the page', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery({ limit: 2 }))
    expect(page.items).toHaveLength(2)
    expect(page.total).toBe(5)
  })

  it('returns an empty page with the real total for limit=0', async () => {
    const repository = await build()

    const page = await repository.listProducts(makeProductQuery({ limit: 0 }))
    expect(page.items).toEqual([])
    expect(page.total).toBe(5)
  })

  it('throws on an unknown sort key before issuing any SQL', async () => {
    const repository = await build()

    const query = { ...makeProductQuery(), sort: 'name; DROP TABLE product--' as unknown as SortKey }
    await expect(repository.listProducts(query)).rejects.toThrow(UnknownSortKeyError)

    // The table is still there, which is the point.
    expect((await repository.listProducts(makeProductQuery())).total).toBe(5)
  })

  it('never loads reviews for a listing', async () => {
    const repository = await build()
    const dataSource = database.require()

    // A listing must be exactly two statements — one COUNT and one SELECT —
    // whatever the page size, so a review join cannot creep back in and turn
    // a page into a query per row. Counted through the DataSource's logger,
    // which every query runner calls; the query builder does not go through
    // `dataSource.query`.
    const statements: string[] = []
    const original = dataSource.logger
    dataSource.logger = {
      ...original,
      logQuery: (query: string) => {
        statements.push(query)
      },
    } as typeof original

    try {
      await repository.listProducts(makeProductQuery())
    } finally {
      dataSource.logger = original
    }

    expect(statements.filter((sql) => /review/i.test(sql))).toEqual([])
    expect(statements).toHaveLength(2)
  })

  it('issues the same two statements whatever the page size', async () => {
    const repository = await build()
    const dataSource = database.require()

    const count = async (limit: number): Promise<number> => {
      const statements: string[] = []
      const original = dataSource.logger
      dataSource.logger = {
        ...original,
        logQuery: (query: string) => {
          statements.push(query)
        },
      } as typeof original
      try {
        await repository.listProducts(makeProductQuery({ limit }))
      } finally {
        dataSource.logger = original
      }
      return statements.length
    }

    expect(await count(1)).toBe(2)
    expect(await count(5)).toBe(2)
  })

  it('loads reviews for a detail, ordered by id', async () => {
    const repository = await build()

    const listing = await repository.listProducts(makeProductQuery({ nameContains: 'Deep' }))
    const detail = await repository.getProductDetail(listing.items[0].id)

    expect(detail?.reviews.map((review) => review.author)).toEqual(['Priya N.', 'Marcus T.'])
    expect(detail?.longDescription).toBe('long')
  })

  it('returns null for a non-numeric or out-of-range id, without touching the driver', async () => {
    const repository = await build()

    expect(await repository.getProduct('abc')).toBeNull()
    expect(await repository.getProductDetail('abc')).toBeNull()
    expect(await repository.getProduct('99999999999')).toBeNull()
  })

  it('returns null for a well-formed id that names no row', async () => {
    const repository = await build()

    expect(await repository.getProduct('2147483647')).toBeNull()
  })
})
