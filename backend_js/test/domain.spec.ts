/**
 * The domain layer and the in-memory repository that stands in for storage.
 *
 * Nothing here touches Postgres or Redis: filtering, sorting, paging and cart
 * arithmetic are business rules, and they are the same rules whichever store
 * is underneath.
 */

import {
  MAX_PAGE_SIZE,
  SortDirection,
  SortKey,
  isProductDetail,
  makeProductQuery,
  makeReview,
} from '../src/domain/catalog'
import { cartSubtotalMinor, lineItemSubtotalMinor, makeLineItem } from '../src/domain/cart'
import { InMemoryRepository } from '../src/domain/fakes'
import { UnknownProductError, UnknownSortKeyError } from '../src/domain/errors'
import { ATOMIC_HABITS, CATALOGUE, DEEP_WORK, TYPESCRIPT_COURSE } from './catalogue-fixtures'

describe('ProductQuery', () => {
  it('applies the documented defaults', () => {
    expect(makeProductQuery()).toEqual({
      nameContains: null,
      categorySlug: null,
      sort: SortKey.NAME,
      direction: SortDirection.ASC,
      limit: 20,
      offset: 0,
    })
  })

  it('rejects a limit above the ceiling rather than clamping it', () => {
    expect(() => makeProductQuery({ limit: MAX_PAGE_SIZE + 1 })).toThrow(RangeError)
    expect(makeProductQuery({ limit: MAX_PAGE_SIZE }).limit).toBe(MAX_PAGE_SIZE)
  })

  it('rejects a negative limit or offset', () => {
    expect(() => makeProductQuery({ limit: -1 })).toThrow(RangeError)
    expect(() => makeProductQuery({ offset: -1 })).toThrow(RangeError)
  })

  it('accepts a zero limit, which asks only for the total', () => {
    expect(makeProductQuery({ limit: 0 }).limit).toBe(0)
  })
})

describe('Review', () => {
  it.each([0, 6, -1])('rejects a rating of %p', (rating) => {
    expect(() => makeReview({ id: '1', author: 'A', rating, body: 'b' })).toThrow(RangeError)
  })

  it.each([1, 3, 5])('accepts a rating of %p', (rating) => {
    expect(makeReview({ id: '1', author: 'A', rating, body: 'b' }).rating).toBe(rating)
  })
})

describe('isProductDetail', () => {
  it('tells a detail from a summary, standing in for a runtime type check', () => {
    expect(isProductDetail(DEEP_WORK)).toBe(true)
    expect(isProductDetail(ATOMIC_HABITS)).toBe(false)
  })
})

describe('Cart arithmetic', () => {
  it('multiplies in integer minor units, never floats', () => {
    const item = makeLineItem(DEEP_WORK, 3)
    expect(lineItemSubtotalMinor(item)).toBe(4497)
    expect(Number.isInteger(lineItemSubtotalMinor(item))).toBe(true)
  })

  it('sums every line', () => {
    const cart = {
      sessionId: 's',
      items: [makeLineItem(DEEP_WORK, 2), makeLineItem(TYPESCRIPT_COURSE, 1)],
    }
    expect(cartSubtotalMinor(cart)).toBe(1499 * 2 + 7900)
  })

  it('is zero for an empty cart', () => {
    expect(cartSubtotalMinor({ sessionId: 's', items: [] })).toBe(0)
  })

  it.each([0, -2])('refuses a line quantity of %p', (quantity) => {
    expect(() => makeLineItem(DEEP_WORK, quantity)).toThrow(RangeError)
  })
})

describe('InMemoryRepository as a ProductRepository', () => {
  const repository = () => new InMemoryRepository(CATALOGUE)

  it('filters by case-insensitive name substring', async () => {
    const page = await repository().listProducts(makeProductQuery({ nameContains: 'deep' }))
    expect(page.items.map((product) => product.id)).toEqual(['1'])
    expect(page.total).toBe(1)
  })

  it('filters by category slug', async () => {
    const page = await repository().listProducts(
      makeProductQuery({ categorySlug: 'online-courses' }),
    )
    expect(page.items.map((product) => product.id)).toEqual(['3'])
  })

  it('sorts by name ascending by default', async () => {
    const page = await repository().listProducts(makeProductQuery())
    expect(page.items.map((product) => product.name)).toEqual([
      'Advanced TypeScript',
      'Atomic Habits',
      'Deep Work',
    ])
  })

  it('sorts by price descending on request', async () => {
    const page = await repository().listProducts(
      makeProductQuery({ sort: SortKey.PRICE, direction: SortDirection.DESC }),
    )
    expect(page.items.map((product) => product.priceMinor)).toEqual([7900, 1499, 1299])
  })

  it('pages without changing the total', async () => {
    const page = await repository().listProducts(makeProductQuery({ limit: 1, offset: 1 }))
    expect(page.items.map((product) => product.name)).toEqual(['Atomic Habits'])
    expect(page.total).toBe(3)
  })

  it('returns an empty page but the real total for limit=0', async () => {
    const page = await repository().listProducts(makeProductQuery({ limit: 0 }))
    expect(page.items).toEqual([])
    expect(page.total).toBe(3)
  })

  it('throws on a sort key nothing maps', async () => {
    const query = { ...makeProductQuery(), sort: 'colour' as unknown as SortKey }
    await expect(repository().listProducts(query)).rejects.toThrow(UnknownSortKeyError)
  })

  it('deduplicates categories and orders them by slug', async () => {
    expect(await repository().listCategories()).toEqual([
      { slug: 'e-books', name: 'E-Books' },
      { slug: 'online-courses', name: 'Online Courses' },
    ])
  })

  it('serves a detail only for a product seeded as one', async () => {
    const repo = repository()
    expect(await repo.getProductDetail('1')).not.toBeNull()
    expect(await repo.getProductDetail('2')).toBeNull()
    expect(await repo.getProduct('2')).not.toBeNull()
  })

  it('returns null for an unknown id rather than throwing', async () => {
    expect(await repository().getProduct('nope')).toBeNull()
  })
})

describe('InMemoryRepository as a CartRepository', () => {
  const repository = () => new InMemoryRepository(CATALOGUE)

  it('starts empty and keeps carts per session', async () => {
    const repo = repository()
    await repo.addItem('session-a', '1', 2)

    expect((await repo.getCart('session-a')).items).toHaveLength(1)
    expect((await repo.getCart('session-b')).items).toHaveLength(0)
  })

  it('increments rather than duplicating an existing line', async () => {
    const repo = repository()
    await repo.addItem('s', '1', 2)
    const cart = await repo.addItem('s', '1', 3)

    expect(cart.items).toHaveLength(1)
    expect(cart.items[0].quantity).toBe(5)
  })

  it('sets an absolute quantity, and removes the line at zero', async () => {
    const repo = repository()
    await repo.addItem('s', '1', 5)
    expect((await repo.setQuantity('s', '1', 2)).items[0].quantity).toBe(2)
    expect((await repo.setQuantity('s', '1', 0)).items).toEqual([])
  })

  it('removing an absent line is a no-op, not an error', async () => {
    const cart = await repository().removeItem('s', '3')
    expect(cart.items).toEqual([])
  })

  it('refuses an unknown product', async () => {
    await expect(repository().addItem('s', 'nope', 1)).rejects.toThrow(UnknownProductError)
  })

  it.each([0, -1])('refuses to add a quantity of %p', async (quantity) => {
    await expect(repository().addItem('s', '1', quantity)).rejects.toThrow(RangeError)
  })
})
