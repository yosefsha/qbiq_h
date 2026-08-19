/**
 * Postgres-backed `ProductRepository`.
 *
 * Satisfies the interface in `src/domain/repositories.ts` against the entities
 * in `src/db/entities`. No TypeORM entity or query builder ever escapes this
 * module — every public method returns a domain object from
 * `src/domain/catalog.ts`, or `null`, matching the storage-agnostic boundary
 * the interface exists to draw.
 *
 * Two mapping decisions worth calling out explicitly:
 *
 * 1. Id type. `product.id` and `review.id` are Postgres `integer` primary
 *    keys; the domain models them as `string`. Going out, `String(row.id)` is
 *    always safe. Coming in, a caller-supplied id may not even be numeric —
 *    e.g. `getProduct('abc')` — and hitting Postgres with that surfaces as a
 *    driver-level `invalid input syntax for type integer`, exactly the kind of
 *    storage error a domain-layer caller must never see. So the id is parsed
 *    and range-checked first; anything that is not a valid int4
 *    short-circuits to `null` before any SQL is issued.
 * 2. Category naming. The `category` table's descriptive column is named
 *    `label`; the domain field is `Category.name`. `toCategory` is the single
 *    place that crosses that naming boundary.
 */

import { Injectable } from '@nestjs/common'
import { DataSource, SelectQueryBuilder } from 'typeorm'

import { CategoryEntity } from '../db/entities/category.entity'
import { ProductEntity } from '../db/entities/product.entity'
import { ReviewEntity } from '../db/entities/review.entity'
import {
  Category,
  Product,
  ProductDetail,
  ProductPage,
  ProductQuery,
  Review,
  SortDirection,
  SortKey,
  makeReview,
} from '../domain/catalog'
import { UnknownSortKeyError } from '../domain/errors'
import { ProductRepository } from '../domain/repositories'

/**
 * Explicit whitelist: the only two columns a `ProductQuery.sort` may resolve
 * to. A sort key is looked up here and never interpolated into SQL, so an
 * unrecognised or hostile value (e.g. `name; DROP TABLE product--`) simply
 * misses this map and raises `UnknownSortKeyError` before any statement is
 * built.
 */
const SORT_COLUMNS: Readonly<Record<SortKey, string>> = {
  [SortKey.NAME]: 'product.name',
  // The entity property, not the `price_minor` column: paging a query with a
  // join is executed as a distinct-id subquery, and the ordering has to be
  // expressed in terms the builder can carry into it. Given a raw column name
  // it cannot, and the query fails at runtime rather than at compile time —
  // which is why `sql-product-repository.spec.ts` sorts by price against a
  // real Postgres.
  [SortKey.PRICE]: 'product.priceMinor',
}

/**
 * Postgres `integer` (int4) bounds. A caller-supplied id outside this range is
 * guaranteed not to match any row, so it is treated the same as a non-numeric
 * id rather than being sent to the driver.
 */
const INT4_MIN = -2_147_483_648
const INT4_MAX = 2_147_483_647

/**
 * Escapes `\`, `%`, and `_` so `needle` is matched as a literal substring.
 *
 * Backslash is escaped first so the escaping of `%`/`_` does not itself
 * introduce a second, unescaped backslash.
 */
export function escapeLike(needle: string): string {
  return needle.replace(/\\/g, '\\\\').replace(/%/g, '\\%').replace(/_/g, '\\_')
}

/**
 * Parses a domain product id into the integer primary key, or `null`.
 *
 * `null` covers a non-numeric id, a non-integer one, and one outside Postgres
 * int4 range — either way no row could match, so no invalid id ever reaches
 * SQL.
 */
export function parseProductId(productId: string): number | null {
  if (!/^-?\d+$/.test(productId.trim())) {
    return null
  }
  const primaryKey = Number(productId.trim())
  if (!Number.isSafeInteger(primaryKey)) {
    return null
  }
  if (primaryKey < INT4_MIN || primaryKey > INT4_MAX) {
    return null
  }
  return primaryKey
}

/** `category.label` (DB) -> `Category.name` (domain) — decision 2 above. */
function toCategory(row: CategoryEntity): Category {
  return { slug: row.slug, name: row.label }
}

function toReview(row: ReviewEntity): Review {
  return makeReview({
    id: String(row.id),
    author: row.author,
    rating: row.rating,
    body: row.body,
  })
}

function toProduct(row: ProductEntity): Product {
  return {
    id: String(row.id),
    name: row.name,
    priceMinor: row.priceMinor,
    currency: row.currency,
    shortDescription: row.shortDescription,
    thumbnailUrl: row.thumbnailUrl,
    category: toCategory(row.category),
  }
}

function toProductDetail(row: ProductEntity): ProductDetail {
  // Reviews are sorted by id for a deterministic order: the join makes no
  // ordering promise and the domain type makes none either, but a stable order
  // still lets callers (and tests) rely on it rather than on incidental
  // database return order.
  const reviews = [...(row.reviews ?? [])]
    .sort((left, right) => left.id - right.id)
    .map(toReview)
  return { ...toProduct(row), longDescription: row.longDescription, reviews }
}

@Injectable()
export class SqlProductRepository implements ProductRepository {
  constructor(private readonly dataSource: DataSource) {}

  // -- ProductRepository ---------------------------------------------

  /**
   * Returns a page of products matching `query`.
   *
   * Issues exactly two statements regardless of page size: one `COUNT` over
   * the filtered set and one bounded `SELECT` for the page itself. Category is
   * loaded through the same join so `product.category` needs no extra query
   * per row; reviews are never touched here, per the interface's no-N+1
   * requirement.
   */
  async listProducts(query: ProductQuery): Promise<ProductPage> {
    const sortColumn = SORT_COLUMNS[query.sort]
    if (sortColumn === undefined) {
      throw new UnknownSortKeyError(query.sort)
    }

    const total = await this.filteredProducts(query).getCount()

    // `limit=0` is a valid request meaning "just tell me the total" — it must
    // return an empty page rather than every row. Short-circuited here because
    // a query builder treats a zero `take` as "unbounded", which would turn
    // the cheapest possible request into a full scan.
    if (query.limit === 0) {
      return { items: [], total }
    }

    const direction = query.direction === SortDirection.DESC ? 'DESC' : 'ASC'
    const rows = await this.filteredProducts(query)
      .orderBy(sortColumn, direction)
      // `name` is not unique in the schema, so the primary key is added as a
      // tiebreaker. Without it, rows tied on the sort column could be dropped
      // or repeated across pages depending on how Postgres happens to order
      // ties.
      .addOrderBy('product.id', 'ASC')
      // `limit`/`offset`, not `take`/`skip`. The latter pages by first
      // selecting a distinct set of ids in a subquery and then fetching those
      // rows — three round trips instead of two — which exists to stop a
      // one-to-many join from multiplying rows and eating the page. The only
      // join here is `product -> category`, which is many-to-one, so each
      // product appears exactly once and the extra query buys nothing. If
      // reviews were ever joined into this listing, that would stop being
      // true — which is one more reason they are not.
      .limit(query.limit)
      .offset(query.offset)
      .getMany()

    return { items: rows.map(toProduct), total }
  }

  /** Returns the summary `Product` for `productId`, or `null`. */
  async getProduct(productId: string): Promise<Product | null> {
    const primaryKey = parseProductId(productId)
    if (primaryKey === null) {
      return null
    }

    const row = await this.dataSource
      .getRepository(ProductEntity)
      .createQueryBuilder('product')
      .innerJoinAndSelect('product.category', 'category')
      .where('product.id = :id', { id: primaryKey })
      .getOne()

    return row === null ? null : toProduct(row)
  }

  /**
   * Returns the full `ProductDetail` for `productId`, or `null`.
   *
   * Reviews are loaded here, and nowhere else — `listProducts` never touches
   * them.
   */
  async getProductDetail(productId: string): Promise<ProductDetail | null> {
    const primaryKey = parseProductId(productId)
    if (primaryKey === null) {
      return null
    }

    const row = await this.dataSource
      .getRepository(ProductEntity)
      .createQueryBuilder('product')
      .innerJoinAndSelect('product.category', 'category')
      .leftJoinAndSelect('product.reviews', 'review')
      .where('product.id = :id', { id: primaryKey })
      .getOne()

    return row === null ? null : toProductDetail(row)
  }

  /**
   * Returns every `Category`, ordered by `slug` for a deterministic listing.
   *
   * A single, unbounded `SELECT` — the category table is small and expected to
   * stay so (it is edited by catalogue maintainers, not Shoppers), so no
   * paging is offered here.
   */
  async listCategories(): Promise<readonly Category[]> {
    const rows = await this.dataSource
      .getRepository(CategoryEntity)
      .createQueryBuilder('category')
      .orderBy('category.slug', 'ASC')
      .getMany()
    return rows.map(toCategory)
  }

  // -- internals ------------------------------------------------------

  /**
   * Builds the filtered-but-unordered `SELECT`, used by both the count query
   * and the page query so the two always see identical filters.
   */
  private filteredProducts(query: ProductQuery): SelectQueryBuilder<ProductEntity> {
    const builder = this.dataSource
      .getRepository(ProductEntity)
      .createQueryBuilder('product')
      .innerJoinAndSelect('product.category', 'category')

    if (query.nameContains) {
      builder.andWhere(`product.name ILIKE :pattern ESCAPE '\\'`, {
        pattern: `%${escapeLike(query.nameContains)}%`,
      })
    }

    if (query.categorySlug !== null) {
      builder.andWhere('category.slug = :slug', { slug: query.categorySlug })
    }

    return builder
  }
}
