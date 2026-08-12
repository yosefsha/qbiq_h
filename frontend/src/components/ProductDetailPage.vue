<script setup lang="ts">
/**
 * The Product detail view: everything known about a single Product plus the
 * Add to Cart action. Replaces the FE-01 stub.
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { apiClient } from '../api/client'
import { useAsyncRequest } from '../composables/useAsyncRequest'
import { formatMoney } from '../money'
import { useCartStore } from '../stores/cart'
import type { ApiError, ProductDetail } from '../types'
import ErrorState from './ErrorState.vue'

interface Props {
  id: string
}

const props = defineProps<Props>()

const router = useRouter()
const cartStore = useCartStore()

const {
  status,
  data: product,
  error,
  execute,
  retry,
} = useAsyncRequest<ProductDetail>(() =>
  apiClient.get<ProductDetail>(`/products/${encodeURIComponent(props.id)}`),
)

const quantity = ref(1)
const addToCartError = ref<ApiError | undefined>(undefined)
const justAdded = ref(false)

// vue-router reuses this component instance across sibling `/products/:id`
// navigations rather than remounting it, so the request and the Add to Cart
// state have to be reset explicitly when the id changes instead of relying
// on a fresh `setup()` run.
watch(
  () => props.id,
  () => {
    quantity.value = 1
    justAdded.value = false
    addToCartError.value = undefined
    void execute()
  },
)

const formattedPrice = computed(() =>
  product.value ? formatMoney(product.value.priceMinor, product.value.currency) : '',
)

function onQuantityChange(): void {
  justAdded.value = false
  addToCartError.value = undefined
}

async function onAddToCart(): Promise<void> {
  addToCartError.value = undefined
  justAdded.value = false
  const result = await cartStore.addItem(props.id, quantity.value)
  if (result.ok) {
    justAdded.value = true
  } else {
    addToCartError.value = result.error
  }
}

/**
 * "Back to Products" has to preserve the catalogue's filters (FE-02 syncs
 * them to the URL's query string), so a plain `<RouterLink to="/">` is
 * wrong — it always lands on an unfiltered `/`. `router.back()` returns to
 * whatever URL the catalogue actually was, filters included, but only makes
 * sense when the previous entry in *this* session really was the catalogue.
 * Otherwise — opened as a deep link, or reached this page after a refresh —
 * there may be no previous entry at all, or it may point somewhere
 * unrelated, and blindly calling `back()` would strand the shopper off-app
 * or on an unexpected page.
 *
 * vue-router's HTML5 history already stores the previous entry's full path
 * (query string included) as `back` on `window.history.state` for exactly
 * this kind of decision, so it's read directly here rather than tracked a
 * second time in component state.
 */
function goToProducts(): void {
  const historyState = window.history.state as { back?: string | null } | null
  const previousPath = historyState?.back
  const previousPathname =
    typeof previousPath === 'string' ? previousPath.split(/[?#]/)[0] : undefined

  if (previousPathname === '/') {
    router.back()
  } else {
    void router.push('/')
  }
}
</script>

<template>
  <section class="flex flex-col gap-6">
    <button
      type="button"
      data-testid="back-to-products-button"
      class="self-start text-sm font-medium text-slate-600 hover:text-slate-900"
      @click="goToProducts"
    >
      &larr; Back to products
    </button>

    <template v-if="status === 'loading' || status === 'idle'">
      <p class="text-slate-600">
        Loading product…
      </p>
    </template>

    <template v-else-if="status === 'error' && error">
      <ErrorState
        :error="error"
        @retry="retry"
      />
    </template>

    <template v-else-if="product">
      <div class="grid grid-cols-1 gap-8 md:grid-cols-2">
        <img
          :src="product.thumbnailUrl"
          :alt="product.name"
          class="aspect-square w-full rounded-lg object-cover"
        >

        <div class="flex flex-col gap-4">
          <p class="text-sm font-semibold tracking-wide text-slate-500 uppercase">
            {{ product.category.name }}
          </p>
          <h1 class="text-2xl font-semibold text-slate-900">
            {{ product.name }}
          </h1>
          <p class="text-xl font-semibold text-slate-900">
            {{ formattedPrice }}
          </p>
          <p class="text-slate-600">
            {{ product.shortDescription }}
          </p>

          <div class="flex items-end gap-3">
            <div class="flex flex-col gap-1">
              <label
                for="quantity"
                class="text-sm font-medium text-slate-700"
              >Quantity</label>
              <input
                id="quantity"
                v-model.number="quantity"
                data-testid="quantity-input"
                type="number"
                min="1"
                class="w-20 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                @change="onQuantityChange"
              >
            </div>
            <button
              type="button"
              data-testid="add-to-cart-button"
              class="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="cartStore.pending"
              @click="onAddToCart"
            >
              {{ cartStore.pending ? 'Adding…' : 'Add to Cart' }}
            </button>
          </div>

          <p
            v-if="justAdded"
            role="status"
            class="text-sm font-medium text-green-700"
          >
            Added to cart.
          </p>
          <ErrorState
            v-if="addToCartError"
            :error="addToCartError"
            @retry="onAddToCart"
          />
        </div>
      </div>

      <section class="flex flex-col gap-2">
        <h2 class="text-lg font-semibold text-slate-900">
          Description
        </h2>
        <p class="whitespace-pre-line text-slate-600">
          {{ product.longDescription }}
        </p>
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="text-lg font-semibold text-slate-900">
          Reviews
        </h2>

        <template v-if="product.reviews.length > 0">
          <ul class="flex flex-col gap-4">
            <li
              v-for="review in product.reviews"
              :key="review.id"
              class="flex flex-col gap-1 rounded-lg border border-slate-200 p-4"
            >
              <div class="flex items-center justify-between">
                <span class="font-medium text-slate-900">{{ review.author }}</span>
                <span class="text-sm text-slate-500">{{ review.rating }} / 5</span>
              </div>
              <p class="text-slate-600">
                {{ review.body }}
              </p>
            </li>
          </ul>
        </template>
        <template v-else>
          <p
            data-testid="reviews-empty"
            class="text-slate-600"
          >
            No reviews yet.
          </p>
        </template>
      </section>
    </template>
  </section>
</template>
