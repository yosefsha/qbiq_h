import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import type { Product } from '../types'
import ProductCard from './ProductCard.vue'

function product(overrides: Partial<Product> = {}): Product {
  return {
    id: '1',
    name: 'Deep Work',
    priceMinor: 14900,
    currency: 'USD',
    shortDescription: 'A guide to focused success.',
    thumbnailUrl: 'https://cdn.example.com/deep-work.jpg',
    category: { slug: 'books', name: 'Books' },
    ...overrides,
  }
}

async function mountCard(overrides: Partial<Product> = {}): Promise<{
  wrapper: ReturnType<typeof mount>
  router: Router
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'catalogue', component: { template: '<div />' } },
      { path: '/products/:id', name: 'product-detail', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()

  const wrapper = mount(ProductCard, {
    props: { product: product(overrides) },
    global: { plugins: [router] },
  })

  return { wrapper, router }
}

describe('ProductCard', () => {
  it('renders the whole card as a single native <a>, not a clickable <div>', async () => {
    const { wrapper } = await mountCard()

    // A real <a href> is Tab-reachable and Enter-activates as native browser
    // behaviour, with no extra tabindex/keydown wiring required. A `<div>`
    // with a click handler would need both bolted on to be keyboard-operable
    // at all, which is exactly the defect this asserts against.
    const link = wrapper.get('a')
    expect(link.attributes('href')).toBe('/products/1')
    expect(wrapper.find('div[role="link"]').exists()).toBe(false)
  })

  it('marks the thumbnail as decorative, since the product name is rendered as visible text right below it', async () => {
    const { wrapper } = await mountCard()

    // Deliberate alt="", not an omitted attribute: the name would otherwise
    // be announced twice (once for the image, once for the heading) for no
    // extra information.
    expect(wrapper.get('img').attributes('alt')).toBe('')
  })

  it("gives the link an accessible name from its text content — the product's name", async () => {
    const { wrapper } = await mountCard({ name: 'Atomic Habits' })

    expect(wrapper.get('a').text()).toContain('Atomic Habits')
  })
})
