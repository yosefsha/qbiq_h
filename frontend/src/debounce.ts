/**
 * A plain debounced-function factory, kept as a pure utility rather than a
 * composable: it holds a single `setTimeout` handle and nothing reactive, so
 * wrapping it in `ref`/lifecycle machinery would add ceremony without buying
 * anything. Callers that use it inside a component are still responsible for
 * calling `cancel()` from `onUnmounted`, exactly like any other timer.
 */
export interface Debounced<Args extends unknown[]> {
  /** Schedules `fn`, cancelling any call scheduled by a previous `run()` that hasn't fired yet. */
  run: (...args: Args) => void
  /** Cancels a pending call, if there is one. Safe to call when idle. */
  cancel: () => void
}

export function debounce<Args extends unknown[]>(
  fn: (...args: Args) => void,
  delayMs: number,
): Debounced<Args> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined

  function cancel(): void {
    if (timeoutId !== undefined) {
      clearTimeout(timeoutId)
      timeoutId = undefined
    }
  }

  function run(...args: Args): void {
    cancel()
    timeoutId = setTimeout(() => {
      timeoutId = undefined
      fn(...args)
    }, delayMs)
  }

  return { run, cancel }
}
