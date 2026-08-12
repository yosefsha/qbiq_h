import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import CataloguePage from './CataloguePage.vue'
import NotFoundPage from './NotFoundPage.vue'

describe('NotFoundPage', () => {
  it('renders a 404 message and a link back to the catalogue', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'catalogue', component: CataloguePage },
        { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundPage },
      ],
    })

    await router.push('/nonexistent')
    await router.isReady()

    const wrapper = mount(NotFoundPage, { global: { plugins: [router] } })

    expect(wrapper.text()).toContain('Page not found')

    const link = wrapper.get('a')
    expect(link.text()).toContain('Back to the catalogue')

    await link.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('catalogue')
  })
})
