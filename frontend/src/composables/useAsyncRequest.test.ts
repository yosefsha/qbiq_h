/* eslint-disable vue/one-component-per-file --
   These are one-line test harnesses whose only job is to give the composable a
   real component lifecycle to be disposed by; the rule is about app components. */
import { mount } from '@vue/test-utils'
import { defineComponent, effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import type { ApiResult } from '../types'
import { useAsyncRequest } from './useAsyncRequest'

describe('useAsyncRequest', () => {
  it('discards a response that lands after its owning component unmounts', async () => {
    let resolve!: (result: ApiResult<{ id: string }>) => void
    const requestFn = vi.fn<() => Promise<ApiResult<{ id: string }>>>(
      () =>
        new Promise((r) => {
          resolve = r
        }),
    )

    let handle!: ReturnType<typeof useAsyncRequest<{ id: string }>>
    const wrapper = mount(
      defineComponent({
        setup() {
          handle = useAsyncRequest(requestFn)
          return () => null
        },
      }),
    )

    wrapper.unmount()
    resolve({ ok: true, data: { id: '1' } })
    await Promise.resolve()
    await Promise.resolve()

    // The view is gone, so writing to its state is pointless work at best and
    // a leak at worst. Cancellation is scoped to the consumer that unmounted.
    expect(handle.data.value).toBeUndefined()
    expect(handle.status.value).toBe('loading')
  })

  it('keeps resolving when an unrelated component unmounts, because it belongs to its own scope', async () => {
    // The counterpart to the test above, and the regression this file was
    // missing: a composable created inside a long-lived scope (a Pinia store)
    // must not be disposed by the unmount of whichever component happened to
    // trigger that scope's creation.
    const scope = effectScope()
    let handle!: ReturnType<typeof useAsyncRequest<{ id: string }>>

    const wrapper = mount(
      defineComponent({
        setup() {
          scope.run(() => {
            handle = useAsyncRequest<{ id: string }>(async () => ({ ok: true, data: { id: '1' } }))
          })
          return () => null
        },
      }),
    )
    wrapper.unmount()

    await handle.execute()

    expect(handle.status.value).toBe('success')
    expect(handle.data.value).toEqual({ id: '1' })
  })

  it('starts loading immediately and resolves to success', async () => {
    const requestFn = vi.fn<() => Promise<ApiResult<{ id: string }>>>(async () => ({
      ok: true,
      data: { id: '1' },
    }))

    const { status, data, error } = useAsyncRequest(requestFn)

    expect(status.value).toBe('loading')
    // Flush the microtask queue so the request issued during setup settles.
    await Promise.resolve()
    await Promise.resolve()

    expect(status.value).toBe('success')
    expect(data.value).toEqual({ id: '1' })
    expect(error.value).toBeUndefined()
    expect(requestFn).toHaveBeenCalledTimes(1)
  })

  it('fails, then recovers when retry() re-issues the request and it succeeds', async () => {
    const requestFn = vi
      .fn<() => Promise<ApiResult<{ id: string }>>>()
      .mockResolvedValueOnce({ ok: false, error: { kind: 'network', message: 'offline' } })
      .mockResolvedValueOnce({ ok: true, data: { id: '42' } })

    const { status, data, error, execute, retry } = useAsyncRequest(requestFn, { immediate: false })

    await execute()

    expect(status.value).toBe('error')
    expect(error.value).toEqual({ kind: 'network', message: 'offline' })
    expect(data.value).toBeUndefined()

    await retry()

    expect(status.value).toBe('success')
    expect(data.value).toEqual({ id: '42' })
    expect(error.value).toBeUndefined()
    expect(requestFn).toHaveBeenCalledTimes(2)
  })

  it('does not issue a request until execute()/retry() is called when immediate is false', () => {
    const requestFn = vi.fn<() => Promise<ApiResult<unknown>>>()

    const { status } = useAsyncRequest(requestFn, { immediate: false })

    expect(status.value).toBe('idle')
    expect(requestFn).not.toHaveBeenCalled()
  })

  it('re-issues on execute() during an in-flight request, and the newest response wins', async () => {
    // This previously asserted the opposite — that a re-entrant execute() was
    // ignored. That silently dropped the call while still resolving as though
    // it had run, so a view re-executing on a route-param change (product 1 ->
    // 2 mid-flight) rendered the first product forever.
    const resolvers: ((result: ApiResult<{ id: string }>) => void)[] = []
    const requestFn = vi.fn<() => Promise<ApiResult<{ id: string }>>>(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve)
        }),
    )

    const { status, data, execute } = useAsyncRequest(requestFn, { immediate: false })

    const firstCall = execute()
    const secondCall = execute()

    expect(requestFn).toHaveBeenCalledTimes(2)

    // The superseded request lands LAST — the stale-response guard has to
    // discard it rather than let it overwrite the newer result.
    resolvers[1]!({ ok: true, data: { id: '2' } })
    resolvers[0]!({ ok: true, data: { id: '1' } })
    await Promise.all([firstCall, secondCall])

    expect(status.value).toBe('success')
    expect(data.value).toEqual({ id: '2' })
  })

  it('clears stale data when a refresh fails, so data and error are never both set', async () => {
    let call = 0
    const requestFn = vi.fn<() => Promise<ApiResult<{ id: string }>>>(async () => {
      call += 1
      return call === 1
        ? { ok: true, data: { id: '1' } }
        : { ok: false, error: { kind: 'http', status: 500, message: 'boom' } }
    })

    const { status, data, error, execute } = useAsyncRequest(requestFn, { immediate: false })

    await execute()
    expect(data.value).toEqual({ id: '1' })

    await execute()

    expect(status.value).toBe('error')
    expect(error.value).toBeDefined()
    expect(data.value).toBeUndefined()
  })

  it('never rejects even if requestFn throws synchronously instead of returning an ApiResult', async () => {
    const requestFn = vi.fn<() => Promise<ApiResult<unknown>>>(() => {
      throw new Error('boom')
    })

    const { status, error, execute } = useAsyncRequest(requestFn, { immediate: false })

    await expect(execute()).resolves.toBeUndefined()

    expect(status.value).toBe('error')
    expect(error.value).toEqual({ kind: 'network', message: 'boom' })
  })
})
