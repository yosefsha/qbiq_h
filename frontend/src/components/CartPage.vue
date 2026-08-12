<script setup lang="ts">
/**
 * The cart view: line items, the server's total, and a mock checkout.
 *
 * Reads and mutates `useCartStore` exclusively — it never calls `apiClient`
 * itself (see `stores/cart.ts`'s module comment for why that store is the
 * single reader/writer of `/api/cart`).
 */
import { computed, onMounted } from 'vue'

import { formatMoney } from '../money'
import { useCartStore } from '../stores/cart'
import CartLineItemRow from './CartLineItemRow.vue'
import ErrorState from './ErrorState.vue'

const cartStore = useCartStore()

onMounted(() => {
  // Guards against re-fetching a Cart another view (App's header badge,
  // ProductDetailPage's Add to Cart) already loaded into the store.
  if (!cartStore.cart) {
    void cartStore.load()
  }
})

const items = computed(() => cartStore.cart?.items ?? [])
const isEmpty = computed(() => cartStore.cart !== undefined && items.value.length === 0)
const total = computed(() =>
  cartStore.cart ? formatMoney(cartStore.cart.totalMinor, cartStore.cart.currency) : undefined,
)
const currency = computed(() => cartStore.cart?.currency)

function onChangeQuantity(productId: string, quantity: number): void {
  void cartStore.changeQuantity(productId, quantity)
}

function onRemove(productId: string): void {
  void cartStore.removeItem(productId)
}

function onCheckout(): void {
  void cartStore.checkout()
}

function onRetry(): void {
  void cartStore.load()
}
</script>

<template>
  <section class="flex flex-col gap-6">
    <h1 class="text-2xl font-semibold text-slate-900">
      Cart
    </h1>

    <ErrorState
      v-if="cartStore.error"
      :error="cartStore.error"
      @retry="onRetry"
    />

    <p
      v-if="!cartStore.cart && cartStore.loadPending"
      class="text-slate-600"
    >
      Loading your cart…
    </p>

    <div
      v-else-if="isEmpty"
      data-test="empty-cart"
      class="flex flex-col items-start gap-3 rounded-lg border border-slate-200 bg-white p-6"
    >
      <p class="text-lg font-medium text-slate-900">
        Your cart is empty
      </p>
      <p class="text-slate-600">
        Add a product from the catalogue to get started.
      </p>
      <RouterLink
        to="/"
        class="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
      >
        Browse the catalogue
      </RouterLink>
    </div>

    <template v-else-if="cartStore.cart && currency">
      <ul class="flex flex-col rounded-lg border border-slate-200 bg-white px-4">
        <CartLineItemRow
          v-for="item in items"
          :key="item.productId"
          :item="item"
          :currency="currency"
          :pending="!!cartStore.itemPending[item.productId]"
          @change-quantity="onChangeQuantity(item.productId, $event)"
          @remove="onRemove(item.productId)"
        />
      </ul>

      <div class="flex items-center justify-between border-t border-slate-200 pt-4">
        <span class="text-lg font-semibold text-slate-900">Total</span>
        <span
          data-test="cart-total"
          class="text-lg font-semibold text-slate-900"
        >
          {{ total }}
        </span>
      </div>

      <button
        type="button"
        data-test="checkout"
        class="self-end rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="cartStore.checkoutPending"
        @click="onCheckout"
      >
        {{ cartStore.checkoutPending ? 'Checking out…' : 'Checkout' }}
      </button>
    </template>
  </section>
</template>
