import { describe, expect, it } from 'vitest'

import router from './index'

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
})
