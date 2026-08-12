import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { apiClient } from './api/client'
import App from './App.vue'
import type { Cart } from './types'

vi.mock('./api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockedApiClient = vi.mocked(apiClient)

const emptyCart: Cart = { items: [], totalMinor: 0, currency: 'USD' }

async function mountApp() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'catalogue', component: { template: '<div />' } },
      { path: '/cart', name: 'cart', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()

  const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
  await flushPromises()

  return { wrapper, router }
}

describe('App', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockedApiClient.get.mockResolvedValue({ ok: true, data: emptyCart })
  })

  it('provides a skip link that jumps to the main landmark, for keyboard users to bypass the repeated nav', async () => {
    const { wrapper } = await mountApp()

    const skipLink = wrapper.get('a[href="#main-content"]')
    expect(skipLink.text()).toBe('Skip to main content')
    expect(wrapper.get('#main-content').element.tagName).toBe('MAIN')
  })

  it('makes the main landmark a focusable route-change target', async () => {
    const { wrapper } = await mountApp()

    const main = wrapper.get('#main-content')
    expect(main.attributes('tabindex')).toBe('-1')
  })

  it('gives every nav link an accessible name from its own visible text', async () => {
    const { wrapper } = await mountApp()

    const nav = wrapper.get('nav')
    const links = nav.findAll('a')
    expect(links.length).toBeGreaterThanOrEqual(3)
    for (const link of links) {
      expect(link.text().trim().length).toBeGreaterThan(0)
    }
  })
})
