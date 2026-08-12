/**
 * Reusable stateful wrapper around a single `apiClient` call. Views hand it a
 * zero-argument function that returns an `ApiResult` — typically a closure
 * over `apiClient.get(...)` plus whatever path/id it needs — and this
 * composable tracks the request's lifecycle and exposes a `retry()` that
 * re-issues that exact same call.
 *
 * `apiClient` already never throws (see `api/client.ts`): every failure mode
 * — offline, a non-2xx status, an unparsable body — comes back as
 * `{ ok: false, error }` rather than a rejection. `execute` still wraps the
 * call in a try/catch so a mistake in a caller-supplied `requestFn` (or a
 * future change to that contract) can never surface as an unhandled promise
 * rejection here.
 */
import { getCurrentInstance, onUnmounted, ref, shallowRef } from 'vue'

import type { ApiError, ApiResult, AsyncRequestStatus } from '../types'

export interface UseAsyncRequestOptions {
  /** Issue the request as soon as the composable runs. Defaults to `true`. */
  immediate?: boolean
}

export interface UseAsyncRequestReturn<T> {
  status: ReturnType<typeof ref<AsyncRequestStatus>>
  data: ReturnType<typeof shallowRef<T | undefined>>
  error: ReturnType<typeof shallowRef<ApiError | undefined>>
  /** Issues (or re-issues) the request. Safe to call while a request is already in flight — it's a no-op then. */
  execute: () => Promise<void>
  /** Re-issues the same request. Intended for a "Retry" button's `@click`. */
  retry: () => Promise<void>
}

function toNetworkError(cause: unknown): ApiError {
  return {
    kind: 'network',
    message: cause instanceof Error ? cause.message : 'An unexpected error occurred',
  }
}

export function useAsyncRequest<T>(
  requestFn: () => Promise<ApiResult<T>>,
  options: UseAsyncRequestOptions = {},
): UseAsyncRequestReturn<T> {
  const status = ref<AsyncRequestStatus>('idle')
  const data = shallowRef<T>()
  const error = shallowRef<ApiError>()

  let disposed = false
  // Guards against a stale response overwriting the state of a newer, still
  // in-flight request (e.g. rapid retry clicks).
  let requestToken = 0

  // Only registered when there's an active component instance, so this
  // composable can also be driven directly in unit tests without Vue's
  // "no active component instance" warning.
  if (getCurrentInstance()) {
    onUnmounted(() => {
      disposed = true
    })
  }

  async function execute(): Promise<void> {
    if (status.value === 'loading') {
      return
    }

    const token = ++requestToken
    status.value = 'loading'
    error.value = undefined

    let result: ApiResult<T>
    try {
      result = await requestFn()
    } catch (cause) {
      result = { ok: false, error: toNetworkError(cause) }
    }

    if (disposed || token !== requestToken) {
      return
    }

    if (result.ok) {
      data.value = result.data
      status.value = 'success'
    } else {
      error.value = result.error
      status.value = 'error'
    }
  }

  function retry(): Promise<void> {
    return execute()
  }

  if (options.immediate ?? true) {
    void execute()
  }

  return { status, data, error, execute, retry }
}
