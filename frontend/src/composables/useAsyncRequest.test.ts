import { describe, expect, it, vi } from 'vitest'

import type { ApiResult } from '../types'
import { useAsyncRequest } from './useAsyncRequest'

describe('useAsyncRequest', () => {
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

  it('ignores a re-entrant execute() call while a request is already in flight', async () => {
    let resolveFirst: (result: ApiResult<{ id: string }>) => void = () => {}
    const requestFn = vi.fn<() => Promise<ApiResult<{ id: string }>>>(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve
        }),
    )

    const { status, execute } = useAsyncRequest(requestFn, { immediate: false })

    const firstCall = execute()
    const secondCall = execute()

    resolveFirst({ ok: true, data: { id: '1' } })
    await Promise.all([firstCall, secondCall])

    expect(status.value).toBe('success')
    expect(requestFn).toHaveBeenCalledTimes(1)
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
