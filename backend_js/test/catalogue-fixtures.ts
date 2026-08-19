/**
 * A small catalogue the route tests share.
 *
 * Two categories and three products is enough to exercise filtering, sorting,
 * paging and the category-slug validation without any of them accidentally
 * passing because there was only ever one row.
 */

import { Product, ProductDetail } from '../src/domain/catalog'

export const EBOOKS = { slug: 'e-books', name: 'E-Books' }
export const COURSES = { slug: 'online-courses', name: 'Online Courses' }

export const DEEP_WORK: ProductDetail = {
  id: '1',
  name: 'Deep Work',
  priceMinor: 1499,
  currency: 'USD',
  shortDescription: 'A practical guide to focus.',
  thumbnailUrl: '/assets/thumbnails/deep-work.svg',
  category: EBOOKS,
  longDescription: 'A framework for training your ability to focus.',
  reviews: [{ id: '10', author: 'Priya N.', rating: 5, body: 'Read it twice.' }],
}

export const ATOMIC_HABITS: Product = {
  id: '2',
  name: 'Atomic Habits',
  priceMinor: 1299,
  currency: 'USD',
  shortDescription: 'Small changes, remarkable results.',
  thumbnailUrl: '/assets/thumbnails/atomic-habits.svg',
  category: EBOOKS,
}

export const TYPESCRIPT_COURSE: Product = {
  id: '3',
  name: 'Advanced TypeScript',
  priceMinor: 7900,
  currency: 'USD',
  shortDescription: 'Types that carry their weight.',
  thumbnailUrl: '/assets/thumbnails/advanced-typescript.svg',
  category: COURSES,
}

export const CATALOGUE: Product[] = [DEEP_WORK, ATOMIC_HABITS, TYPESCRIPT_COURSE]
