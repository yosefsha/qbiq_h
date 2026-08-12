import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import router from './index'

/** Waits for the `requestAnimationFrame` the `afterEach` focus hook defers into. */
function waitForFocusMove(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

describe('router', () => {
  it('resolves an unmatched path to the not-found route', async () => {
    await router.push('/this/path/does/not/exist')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('not-found')
  })

  it('resolves known routes normally, unaffected by the catch-all', async () => {
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('catalogue')

    await router.push('/cart')
    expect(router.currentRoute.value.name).toBe('cart')
  })

  describe('focus on navigation', () => {
    // A real `<main id="main-content">` (App.vue) has to exist for the
    // `afterEach` hook's `document.getElementById('main-content')?.focus()`
    // to have anything to move focus to.
    let main: HTMLElement

    beforeEach(() => {
      main = document.createElement('main')
      main.id = 'main-content'
      main.tabIndex = -1
      document.body.appendChild(main)
    })

    afterEach(() => {
      main.remove()
    })

    it('moves focus to the main landmark after a navigation, so it is never left stranded on the previous view', async () => {
      await router.push('/')
      await router.isReady()
      document.body.focus() // Simulate focus being anywhere else beforehand.

      await router.push('/cart')
      await waitForFocusMove()

      expect(document.activeElement).toBe(main)
    })

    it('moves focus again on a param-only navigation (e.g. one product to another)', async () => {
      await router.push('/products/1')
      await router.isReady()
      await waitForFocusMove()
      main.blur()

      await router.push('/products/2')
      await waitForFocusMove()

      expect(document.activeElement).toBe(main)
    })

    it("sets document.title from the route's meta so the browser tab and some screen readers announce the change too", async () => {
      await router.push('/cart')
      await router.isReady()

      expect(document.title).toBe('Cart · qbiq_h')

      await router.push('/')
      expect(document.title).toBe('Catalogue · qbiq_h')
    })
  })
})
