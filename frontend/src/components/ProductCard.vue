<script setup lang="ts">
/** One catalogue listing row, linking to its detail page (FE-03 owns what's there). */
import { computed } from 'vue'

import { formatMoney } from '../money'
import type { Product } from '../types'

interface Props {
  product: Product
}

const props = defineProps<Props>()

const price = computed(() => formatMoney(props.product.priceMinor, props.product.currency))
</script>

<template>
  <RouterLink
    :to="`/products/${product.id}`"
    class="flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-white transition hover:border-slate-300 hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
  >
    <!-- Decorative: the product name right below is the same information in
         text, and the whole card is a single link to the same destination —
         a screen reader announcing the name twice (image, then heading) adds
         noise without adding information. -->
    <img
      :src="product.thumbnailUrl"
      alt=""
      class="aspect-video w-full bg-slate-100 object-cover"
      loading="lazy"
    >
    <div class="flex flex-1 flex-col gap-2 p-4">
      <span class="text-xs font-medium tracking-wide text-slate-500 uppercase">
        {{ product.category.name }}
      </span>
      <h2 class="font-semibold text-slate-900">
        {{ product.name }}
      </h2>
      <p class="line-clamp-2 flex-1 text-sm text-slate-600">
        {{ product.shortDescription }}
      </p>
      <p class="font-semibold text-slate-900">
        {{ price }}
      </p>
    </div>
  </RouterLink>
</template>
