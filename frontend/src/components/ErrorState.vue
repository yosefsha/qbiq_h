<script setup lang="ts">
/**
 * Reusable error presentation for any view driven by `useAsyncRequest`.
 * Renders a message appropriate to the failure kind and, when the failure
 * could plausibly be transient, a "Retry" button that emits `retry` so the
 * consuming view can re-issue the failed request.
 */
import { computed } from 'vue'

import { describeApiError } from '../errorPresentation'
import type { ApiError } from '../types'

interface Props {
  error: ApiError
}

interface Emits {
  (e: 'retry'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const presentation = computed(() => describeApiError(props.error))

function onRetry(): void {
  emit('retry')
}
</script>

<template>
  <section
    class="flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4"
    :data-error-kind="presentation.kind"
    role="alert"
  >
    <div class="flex flex-col gap-1">
      <h2 class="font-semibold text-red-900">
        {{ presentation.title }}
      </h2>
      <p class="text-sm text-red-700">
        {{ presentation.message }}
      </p>
    </div>
    <button
      v-if="presentation.retryable"
      type="button"
      class="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
      @click="onRetry"
    >
      Retry
    </button>
  </section>
</template>
