import { describe, expect, it } from 'vitest'

import { describeApiError } from './errorPresentation'
import type { ApiError } from './types'

describe('describeApiError', () => {
  it('marks a 404 as not retryable and titles it "Not found"', () => {
    const error: ApiError = { kind: 'http', status: 404, message: 'Product not found' }

    expect(describeApiError(error)).toEqual({
      kind: 'http',
      title: 'Not found',
      message: 'Product not found',
      retryable: false,
    })
  })

  it('marks a 500 as retryable, distinct from a 404', () => {
    const error: ApiError = { kind: 'http', status: 500, message: 'Internal Server Error' }

    expect(describeApiError(error)).toEqual({
      kind: 'http',
      title: 'Request failed (500)',
      message: 'Internal Server Error',
      retryable: true,
    })
  })

  it('marks a non-404 client error as not retryable', () => {
    const error: ApiError = { kind: 'http', status: 400, message: 'Bad request' }

    expect(describeApiError(error).retryable).toBe(false)
  })

  it('marks a transport/network failure as retryable and distinct from an HTTP failure', () => {
    const error: ApiError = { kind: 'network', message: 'Failed to fetch' }

    expect(describeApiError(error)).toEqual({
      kind: 'network',
      title: "Can't reach the server",
      message: 'Failed to fetch',
      retryable: true,
    })
  })

  it('marks a parse failure as retryable and distinct from the other two kinds', () => {
    const error: ApiError = { kind: 'parse', message: 'Unexpected token' }

    expect(describeApiError(error)).toEqual({
      kind: 'parse',
      title: 'Unexpected response',
      message: 'Unexpected token',
      retryable: true,
    })
  })

  it('produces three distinct presentations for the three failure kinds', () => {
    const presentations = [
      describeApiError({ kind: 'http', status: 404, message: 'x' }),
      describeApiError({ kind: 'network', message: 'x' }),
      describeApiError({ kind: 'parse', message: 'x' }),
    ]

    const titles = new Set(presentations.map((p) => p.title))
    expect(titles.size).toBe(3)
  })

  it('falls back to a generic message when the error carries no message', () => {
    const error: ApiError = { kind: 'network', message: '' }

    expect(describeApiError(error).message).toBe('Check your connection and try again.')
  })
})
