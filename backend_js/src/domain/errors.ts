/**
 * Domain-level errors raised by repository implementations.
 *
 * These are storage-agnostic on purpose: a SQL-backed `ProductRepository`
 * translates a missing row into `UnknownProductError`, a Redis-backed
 * `CartRepository` does the same, and callers (controllers, other business
 * logic) only ever need to catch these — never a driver-specific error from
 * TypeORM or ioredis.
 */

import { pyRepr } from '../common/py-repr'

/** Base class for all errors raised by domain repositories. */
export class DomainError extends Error {}

/**
 * Raised when a `ProductQuery.sort` value names no known ordering.
 *
 * `ProductQuery.sort` is typed as `SortKey`, but nothing at runtime stops a
 * caller constructing a query with an invalid value (e.g. a raw string read
 * from an unvalidated query parameter). Repository implementations must throw
 * this rather than silently falling back to a default order.
 */
export class UnknownSortKeyError extends DomainError {
  constructor(readonly sortKey: unknown) {
    super(`Unknown sort key: ${pyRepr(String(sortKey))}`)
    this.name = 'UnknownSortKeyError'
  }
}

/** Raised when an operation references a product id that does not exist. */
export class UnknownProductError extends DomainError {
  constructor(readonly productId: string) {
    super(`Unknown product id: ${pyRepr(productId)}`)
    this.name = 'UnknownProductError'
  }
}

/**
 * Raised when a `category` filter names a slug no `Category` has.
 *
 * An HTTP input-validation concern, not a storage failure — nothing about the
 * repository failed, the caller-supplied filter value just names nothing.
 * Thrown by `ProductCatalogService` before any repository call that would use
 * the filter, and mapped to 422: an empty result set and an invalid filter are
 * different outcomes and must not look identical to the client.
 */
export class UnknownCategoryError extends DomainError {
  constructor(readonly slug: string) {
    super(`Unknown category slug: ${pyRepr(slug)}`)
    this.name = 'UnknownCategoryError'
  }
}
