<script setup lang="ts">
// Root component: layout shell only. Feature views own their own content.
import { onMounted } from 'vue'

import CartBadge from './components/CartBadge.vue'
import { useCartStore } from './stores/cart'

const cartStore = useCartStore()

onMounted(() => {
  // The one place the Cart is loaded eagerly, so the header badge, CartPage,
  // and the product detail page's Add to Cart all start from the same
  // server response instead of each issuing their own `/api/cart` request.
  void cartStore.load()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50">
    <header class="border-b border-slate-200 bg-white">
      <nav class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-4">
        <RouterLink
          to="/"
          class="text-lg font-bold text-slate-900"
        >
          qbiq_h
        </RouterLink>
        <RouterLink
          to="/"
          class="text-slate-600 hover:text-slate-900"
        >
          Catalogue
        </RouterLink>
        <RouterLink
          to="/cart"
          class="flex items-center gap-1.5 text-slate-600 hover:text-slate-900"
        >
          Cart
          <CartBadge />
        </RouterLink>
      </nav>
    </header>
    <main class="mx-auto max-w-4xl px-4 py-8">
      <RouterView />
    </main>
  </div>
</template>
