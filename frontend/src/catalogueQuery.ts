/**
 * The catalogue's server-side query, and the pure functions that translate
 * it to and from a URL's query parameters.
 *
 * Kept out of `stores/catalogue.ts` and `CataloguePage.vue` on purpose: the
 * URL <-> query and query <-> `URLSearchParams` mappings are exactly the
 * "parsing/transformation logic" the project's coding standards ask to be
 * pure functions rather than inline component code, and having them pure
 * makes the URL round-trip testable without mounting anything.
 *
 * `category` is deliberately passed through unvalidated: the API is the only
 * source of truth for which slugs exist (never a hardcoded list here), so an
 * unknown slug is sent as-is and surfaces as the 422 the server returns for
 * it. `sort`/`direction`, by contrast, are a fixed enum the client already
 * knows in full, so a garbage value typed into the URL by hand is dropped
 * back to "unset" here rather than forwarded to fail server-side.
 */
import type { LocationQuery, LocationQueryRaw, LocationQueryValue } from 'vue-router'

export type ProductSortField = 'name' | 'price'
export type SortDirection = 'asc' | 'desc'

/** The catalogue's current server-side query, mirrored in both the store and the URL. */
export interface CatalogueQuery {
  name: string
  category: string | undefined
  sort: ProductSortField | undefined
  direction: SortDirection | undefined
  limit: number
  offset: number
}

/** Page size. Well under the API's `limit` max of 100. */
export const DEFAULT_LIMIT = 12

export const DEFAULT_CATALOGUE_QUERY: CatalogueQuery = {
  name: '',
  category: undefined,
  sort: undefined,
  direction: undefined,
  limit: DEFAULT_LIMIT,
  offset: 0,
}

function isSortField(value: string): value is ProductSortField {
  return value === 'name' || value === 'price'
}

function isSortDirection(value: string): value is SortDirection {
  return value === 'asc' || value === 'desc'
}

/** A `LocationQuery` value can be a single string, `null`, or an array of either; only the first wins. */
function firstString(
  value: LocationQueryValue | LocationQueryValue[] | undefined,
): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value
  return raw ?? undefined
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function parseNonNegativeInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback
}

/** Restores a `CatalogueQuery` from a route's query parameters, defaulting anything missing or malformed. */
export function parseCatalogueQuery(routeQuery: LocationQuery): CatalogueQuery {
  const name = firstString(routeQuery.name) ?? ''
  const category = firstString(routeQuery.category)
  const sortRaw = firstString(routeQuery.sort)
  const directionRaw = firstString(routeQuery.direction)

  return {
    name,
    category: category || undefined,
    sort: sortRaw !== undefined && isSortField(sortRaw) ? sortRaw : undefined,
    direction: directionRaw !== undefined && isSortDirection(directionRaw) ? directionRaw : undefined,
    limit: parsePositiveInt(firstString(routeQuery.limit), DEFAULT_LIMIT),
    offset: parseNonNegativeInt(firstString(routeQuery.offset), 0),
  }
}

/**
 * Serialises a `CatalogueQuery` to route query params, omitting anything at
 * its default so an unfiltered view stays at a bare `/`. Key order is fixed
 * (name, category, sort, direction, limit, offset) so two equivalent queries
 * always serialise identically, which is what lets the URL <-> store
 * watchers compare by value without an infinite loop (see `CataloguePage.vue`).
 */
export function toRouteQuery(query: CatalogueQuery): LocationQueryRaw {
  const routeQuery: LocationQueryRaw = {}
  if (query.name) routeQuery.name = query.name
  if (query.category) routeQuery.category = query.category
  if (query.sort) routeQuery.sort = query.sort
  if (query.direction) routeQuery.direction = query.direction
  if (query.limit !== DEFAULT_LIMIT) routeQuery.limit = String(query.limit)
  if (query.offset !== 0) routeQuery.offset = String(query.offset)
  return routeQuery
}

/** Builds the `GET /api/products` query string for a `CatalogueQuery`. Always sends `limit`/`offset`. */
export function buildProductsSearchParams(query: CatalogueQuery): string {
  const params = new URLSearchParams()
  if (query.name) params.set('name', query.name)
  if (query.category) params.set('category', query.category)
  if (query.sort) params.set('sort', query.sort)
  if (query.direction) params.set('direction', query.direction)
  params.set('limit', String(query.limit))
  params.set('offset', String(query.offset))
  return params.toString()
}
