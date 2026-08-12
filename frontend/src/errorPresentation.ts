/**
 * Pure mapping from a typed `ApiError` (see `api/client.ts`) to what a
 * shopper should see on screen. Kept outside any component per the project's
 * "parsing/transformation logic lives in pure functions" rule, and covered
 * directly by unit tests rather than through component rendering.
 */
import type { ApiError, ErrorPresentation } from './types'

const FALLBACK_NETWORK_MESSAGE = "Check your connection and try again."
const FALLBACK_PARSE_MESSAGE = 'The server sent a response the app could not understand.'
const FALLBACK_NOT_FOUND_MESSAGE = "The thing you're looking for doesn't exist."
const FALLBACK_HTTP_MESSAGE = 'Something went wrong on the server.'

/** 5xx statuses are the server's fault and are often transient — worth retrying. */
function isRetryableHttpStatus(status: number): boolean {
  return status >= 500
}

export function describeApiError(error: ApiError): ErrorPresentation {
  switch (error.kind) {
    case 'network':
      return {
        kind: 'network',
        title: "Can't reach the server",
        message: error.message || FALLBACK_NETWORK_MESSAGE,
        retryable: true,
      }

    case 'parse':
      return {
        kind: 'parse',
        title: 'Unexpected response',
        message: error.message || FALLBACK_PARSE_MESSAGE,
        retryable: true,
      }

    case 'http':
      if (error.status === 404) {
        return {
          kind: 'http',
          title: 'Not found',
          message: error.message || FALLBACK_NOT_FOUND_MESSAGE,
          retryable: false,
        }
      }
      return {
        kind: 'http',
        title: `Request failed (${error.status})`,
        message: error.message || FALLBACK_HTTP_MESSAGE,
        retryable: isRetryableHttpStatus(error.status),
      }
  }
}
