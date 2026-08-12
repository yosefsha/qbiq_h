import { describe, expect, it } from 'vitest'
import type { LocationQuery, LocationQueryRaw } from 'vue-router'

import {
  buildProductsSearchParams,
  DEFAULT_CATALOGUE_QUERY,
  parseCatalogueQuery,
  toRouteQuery,
  type CatalogueQuery,
} from './catalogueQuery'

// `toRouteQuery` returns `LocationQueryRaw` (as `router.replace` expects), which
// permits values `LocationQuery` doesn't (e.g. `number`, `undefined`). In
// practice the router normalises a navigation's query to `LocationQuery`
// before `route.query` ever reflects it, and `toRouteQuery` never actually
// emits those extra value kinds — so this cast is safe for round-tripping
// through `parseCatalogueQuery` in a test.
function asRouteQuery(raw: LocationQueryRaw): LocationQuery {
  return raw as LocationQuery
}

describe('parseCatalogueQuery', () => {
  it('defaults to an unfiltered first page for an empty route query', () => {
    expect(parseCatalogueQuery({})).toEqual(DEFAULT_CATALOGUE_QUERY)
  })

  it('restores every field from a fully-populated route query', () => {
    const parsed = parseCatalogueQuery({
      name: 'flow',
      category: 'software',
      sort: 'price',
      direction: 'desc',
      limit: '24',
      offset: '48',
    })

    expect(parsed).toEqual({
      name: 'flow',
      category: 'software',
      sort: 'price',
      direction: 'desc',
      limit: 24,
      offset: 48,
    })
  })

  it('passes an unrecognised category slug through unvalidated, for the server to reject', () => {
    // No hardcoded category list on the client — an unknown slug is the
    // server's call (422), not something filtered out here.
    expect(parseCatalogueQuery({ category: 'not-a-real-category' }).category).toBe(
      'not-a-real-category',
    )
  })

  it('drops an invalid sort/direction rather than forwarding it to the API', () => {
    const parsed = parseCatalogueQuery({ sort: 'popularity', direction: 'sideways' })

    expect(parsed.sort).toBeUndefined()
    expect(parsed.direction).toBeUndefined()
  })

  it('falls back to defaults for a non-numeric limit/offset', () => {
    const parsed = parseCatalogueQuery({ limit: 'lots', offset: 'many' })

    expect(parsed.limit).toBe(DEFAULT_CATALOGUE_QUERY.limit)
    expect(parsed.offset).toBe(0)
  })

  it('takes the first value when a query param repeats', () => {
    expect(parseCatalogueQuery({ name: ['first', 'second'] }).name).toBe('first')
  })
})

describe('toRouteQuery', () => {
  it('produces an empty route query for the default query, keeping "/" clean', () => {
    expect(toRouteQuery(DEFAULT_CATALOGUE_QUERY)).toEqual({})
  })

  it('includes only the fields that differ from their default', () => {
    const query: CatalogueQuery = {
      ...DEFAULT_CATALOGUE_QUERY,
      name: 'flow',
      offset: 24,
    }

    expect(toRouteQuery(query)).toEqual({ name: 'flow', offset: '24' })
  })
})

describe('round-trip', () => {
  it('parseCatalogueQuery(toRouteQuery(q)) reproduces q for an arbitrary query', () => {
    const query: CatalogueQuery = {
      name: 'course',
      category: 'education',
      sort: 'price',
      direction: 'asc',
      limit: 24,
      offset: 48,
    }

    expect(parseCatalogueQuery(asRouteQuery(toRouteQuery(query)))).toEqual(query)
  })

  it('round-trips the default query too', () => {
    expect(parseCatalogueQuery(asRouteQuery(toRouteQuery(DEFAULT_CATALOGUE_QUERY)))).toEqual(
      DEFAULT_CATALOGUE_QUERY,
    )
  })
})

describe('buildProductsSearchParams', () => {
  it('always sends limit and offset, and omits unset filters', () => {
    expect(buildProductsSearchParams(DEFAULT_CATALOGUE_QUERY)).toBe(
      `limit=${DEFAULT_CATALOGUE_QUERY.limit}&offset=0`,
    )
  })

  it('sends every set filter alongside limit/offset', () => {
    const query: CatalogueQuery = {
      name: 'flow',
      category: 'books',
      sort: 'name',
      direction: 'desc',
      limit: 20,
      offset: 40,
    }

    expect(buildProductsSearchParams(query)).toBe(
      'name=flow&category=books&sort=name&direction=desc&limit=20&offset=40',
    )
  })
})
