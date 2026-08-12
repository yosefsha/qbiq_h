<script setup lang="ts">
/**
 * Header cart badge. Reads `useCartStore` only — it never issues its own
 * `/api/cart` request, so it always reflects whatever the store's most
 * recent response was, wherever that response came from (App's initial
 * `load()`, a quantity change on `CartPage`, an "Add to Cart" on the product
 * detail page, ...).
 */
import { computed } from 'vue'

import { useCartStore } from '../stores/cart'

const cartStore = useCartStore()

const itemCount = computed(() => cartStore.itemCount)
</script>

<template>
  <span
    v-if="itemCount > 0"
    data-test="cart-badge-count"
    class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-900 px-1.5 text-xs font-semibold text-white"
  >
    {{ itemCount }}
  </span>
</template>
