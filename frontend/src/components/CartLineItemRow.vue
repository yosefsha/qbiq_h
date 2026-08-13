<script setup lang="ts">
/**
 * One row of `CartPage`'s line-item list. Purely presentational: it renders
 * a `CartLineItem` and emits intent (`change-quantity`, `remove`) rather
 * than talking to the cart store directly, so the store stays the only
 * thing that decides what an optimistic update or a rollback looks like.
 */
import { computed } from 'vue'

import { formatMoney } from '../money'
import type { CartLineItem, CurrencyCode } from '../types'

interface Props {
  item: CartLineItem
  currency: CurrencyCode
  /** True while this row's own add/change/remove request is in flight. */
  pending: boolean
}

interface Emits {
  /** Requests the line's quantity become `quantity`. May be < 1: the store
   * decides whether that is a `PATCH` or a `DELETE`, not this component. */
  (e: 'change-quantity', quantity: number): void
  (e: 'remove'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const unitPrice = computed(() => formatMoney(props.item.unitPriceMinor, props.currency))
const subtotal = computed(() => formatMoney(props.item.subtotalMinor, props.currency))

function decrement(): void {
  emit('change-quantity', props.item.quantity - 1)
}

function increment(): void {
  emit('change-quantity', props.item.quantity + 1)
}

function remove(): void {
  emit('remove')
}
</script>

<template>
  <!-- Two layouts, because one did not fit. The four-column row is fixed-width
       in three of them — the quantity stepper is 96px, the subtotal 80px, the
       Remove button about 55px, plus 48px of gutters — so on a 375px phone the
       name column was left with roughly 64px, and on a 320px one with almost
       nothing. The name did not overflow, it collapsed to a couple of
       characters per line, which reads as a rendering fault rather than a
       narrow screen.

       Below `sm` the name takes a row of its own and the controls sit beneath
       it; from `sm` up the original single row returns. -->
  <li
    class="grid grid-cols-[1fr_auto_auto] items-center gap-x-4 gap-y-3 border-b border-line py-4 last:border-b-0 sm:grid-cols-[1fr_auto_auto_auto] sm:gap-y-0"
    :data-product-id="item.productId"
  >
    <div class="col-span-3 flex flex-col sm:col-span-1">
      <span class="font-medium text-ink">{{ item.name }}</span>
      <span class="text-sm text-muted">{{ unitPrice }} each</span>
    </div>

    <div class="flex items-center gap-2">
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center rounded-md border border-line text-body hover:bg-cream focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50 sm:h-8 sm:w-8"
        :disabled="pending"
        :aria-label="`Decrease quantity of ${item.name}`"
        @click="decrement"
      >
        −
      </button>
      <span
        class="w-6 text-center tabular-nums text-ink"
        data-test="quantity"
      >
        {{ item.quantity }}
      </span>
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center rounded-md border border-line text-body hover:bg-cream focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50 sm:h-8 sm:w-8"
        :disabled="pending"
        :aria-label="`Increase quantity of ${item.name}`"
        @click="increment"
      >
        +
      </button>
    </div>

    <span
      class="w-20 text-right font-medium text-ink"
      data-test="line-subtotal"
    >
      {{ subtotal }}
    </span>

    <button
      type="button"
      class="text-sm font-medium text-red-600 hover:text-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-800 disabled:cursor-not-allowed disabled:opacity-50"
      :disabled="pending"
      :aria-label="`Remove ${item.name} from cart`"
      @click="remove"
    >
      Remove
    </button>
  </li>
</template>
