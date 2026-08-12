/**
 * The single wrapper around `fetch` for the whole app. No component or
 * store may import `fetch` directly — they call `apiClient` instead and
 * branch on the returned `ApiResult`, never on a raw `Response`.
 *
 * `credentials: 'include'` is required on every request: the backend
 * recognises a Shopper via an anonymous, `HttpOnly` session cookie rather
 * than a bearer token (see docs/adr/ADR-001-server-owned-cart.md), and
 * `fetch` only attaches cookies when explicitly told to.
 */
import type { ApiResult } from '../types'

/** Same-origin by default: the SPA and API share an origin in production. */
const DEFAULT_BASE_URL = '/api'

function resolveBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL
}

/** Joins a base URL and a request path without ever producing a double slash. */
export function joinUrl(base: string, path: string): string {
  const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedBase}${normalizedPath}`
}

/** Extracts a human-readable message from an error response's JSON body, if any. */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.clone().json()
    if (
      body !== null &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'string'
    ) {
      return (body as { detail: string }).detail
    }
  } catch {
    // Body wasn't JSON (or was empty) — fall back to the status text below.
  }
  return response.statusText || `Request failed with status ${response.status}`
}

/** Parses a response body as JSON, tolerating an empty body (e.g. 204 No Content). */
async function readJsonBody<T>(response: Response): Promise<T | undefined> {
  const text = await response.text()
  return text ? (JSON.parse(text) as T) : undefined
}

function toErrorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const url = joinUrl(resolveBaseUrl(), path)

  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch (cause) {
    return {
      ok: false,
      error: { kind: 'network', message: toErrorMessage(cause, 'Network request failed') },
    }
  }

  if (!response.ok) {
    return {
      ok: false,
      error: { kind: 'http', status: response.status, message: await readErrorMessage(response) },
    }
  }

  try {
    const data = await readJsonBody<T>(response)
    if (data === undefined) {
      // An empty body cannot satisfy `T`. Casting `undefined` to `T` here would
      // hand callers a value the type system swears is a Cart, so the first
      // property access crashes at runtime with the compiler having signed off.
      // Every endpoint in this API returns a body — a 204 is a contract
      // violation, so report it as one.
      return {
        ok: false,
        error: { kind: 'parse', message: 'Expected a JSON response body but it was empty' },
      }
    }
    return { ok: true, data }
  } catch (cause) {
    return {
      ok: false,
      error: { kind: 'parse', message: toErrorMessage(cause, 'Failed to parse response body') },
    }
  }
}

function toJsonBody(body: unknown): BodyInit | undefined {
  return body === undefined ? undefined : JSON.stringify(body)
}

export const apiClient = {
  get: <T>(path: string): Promise<ApiResult<T>> => request<T>(path, { method: 'GET' }),

  post: <T>(path: string, body?: unknown): Promise<ApiResult<T>> =>
    request<T>(path, { method: 'POST', body: toJsonBody(body) }),

  put: <T>(path: string, body?: unknown): Promise<ApiResult<T>> =>
    request<T>(path, { method: 'PUT', body: toJsonBody(body) }),

  // Required by `PATCH /api/cart/items/{productId}`, the only way to change a
  // line's quantity. Its absence would have forced the cart store to reach for
  // `fetch` directly, which this module exists to prevent.
  patch: <T>(path: string, body?: unknown): Promise<ApiResult<T>> =>
    request<T>(path, { method: 'PATCH', body: toJsonBody(body) }),

  delete: <T>(path: string): Promise<ApiResult<T>> => request<T>(path, { method: 'DELETE' }),
}
