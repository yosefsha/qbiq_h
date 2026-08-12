import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { debounce } from './debounce'

describe('debounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('waits for the delay before calling fn', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    debounced.run('a')
    expect(fn).not.toHaveBeenCalled()

    vi.advanceTimersByTime(299)
    expect(fn).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledExactlyOnceWith('a')
  })

  it('cancels a pending call superseded by a newer run()', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    debounced.run('first')
    vi.advanceTimersByTime(200)
    debounced.run('second')
    vi.advanceTimersByTime(200)
    expect(fn).not.toHaveBeenCalled()

    vi.advanceTimersByTime(100)
    expect(fn).toHaveBeenCalledExactlyOnceWith('second')
  })

  it('does nothing if cancelled before the delay elapses', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    debounced.run('a')
    debounced.cancel()
    vi.advanceTimersByTime(1000)

    expect(fn).not.toHaveBeenCalled()
  })

  it('tolerates cancel() when idle', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    expect(() => debounced.cancel()).not.toThrow()
  })
})
