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
import { getCurrentScope, onScopeDispose, ref, shallowRef } from 'vue'
import type { Ref, ShallowRef } from 'vue'

import type { ApiError, ApiResult, AsyncRequestStatus } from '../types'

export interface UseAsyncRequestOptions {
  /** Issue the request as soon as the composable runs. Defaults to `true`. */
  immediate?: boolean
}

export interface UseAsyncRequestReturn<T> {
  // Written out rather than `ReturnType<typeof ref<AsyncRequestStatus>>`, which
  // resolves to `Ref<AsyncRequestStatus | undefined>` — TypeScript picks ref's
  // no-argument overload — advertising an `undefined` status that can never
  // occur and that every consumer would have to assert away.
  status: Ref<AsyncRequestStatus>
  data: ShallowRef<T | undefined>
  error: ShallowRef<ApiError | undefined>
  /**
   * Issues (or re-issues) the request. Calling it while one is in flight
   * starts a new request; the newest one wins and older responses are
   * discarded when they land.
   */
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

  // Bound to the current *effect scope*, not to the current component
  // instance. The difference is the whole bug this guards against.
  //
  // `getCurrentInstance()` inside a Pinia setup store returns the component
  // that happened to instantiate the store — Pinia runs the store's setup
  // during that component's setup, and an effect scope does not clear the
  // current instance. So `onUnmounted` here bound the *store's* disposal to
  // the lifetime of one component. The catalogue store is created by
  // CataloguePage; navigating into a product unmounted it, `disposed` flipped
  // to true permanently, and every later response was discarded as stale by
  // the guard below. The request succeeded, the status never left `loading`,
  // and the catalogue showed skeletons forever on the way back.
  //
  // A scope is the right unit: a component's scope is disposed when it
  // unmounts (so a view driving this directly still cancels), while a store's
  // own scope outlives every component that uses it. `onScopeDispose` is also
  // a no-op outside any scope, so the previous instance check is unnecessary.
  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true
    })
  }

  async function execute(): Promise<void> {
    // Deliberately NOT skipped when a request is already in flight. Bailing out
    // there dropped the call silently and still resolved as though it had run:
    // a view re-executing on a route-param change (product 1 -> 2 mid-flight)
    // never issued the second request and rendered the first product forever.
    // Overlap is instead resolved below by the token — newest request wins.
    const token = ++requestToken
    status.value = 'loading'
    error.value = undefined

    let result: ApiResult<T>
    try {
      result = await requestFn()
    } catch (cause) {
      result = { ok: false, error: toNetworkError(cause) }
    }

    // A superseded response must not overwrite the newer request's state.
    if (disposed || token !== requestToken) {
      return
    }

    if (result.ok) {
      data.value = result.data
      status.value = 'success'
    } else {
      // Cleared so that exactly one of `data`/`error` is ever populated.
      // Leaving it meant a failed refresh rendered stale content beside an
      // error banner, with no way for a view to tell which to trust.
      data.value = undefined
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
