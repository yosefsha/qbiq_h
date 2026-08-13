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
    <!-- Visually hidden until focused: lets a keyboard user jump past the
         repeated header nav straight to the view's content, rather than
         tabbing through "Catalogue" / "Cart" on every page. -->
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-slate-900 focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-white"
    >
      Skip to main content
    </a>
    <!-- Sticky, because the Cart lives in here. Scrolled down a long
         catalogue, the only route to the Cart was to scroll back to the top,
         and the badge that tells a Shopper what is in it was off-screen for
         most of the page. `z-40` sits under the skip link's `z-50` so a
         focused skip link is never covered by the header it skips. -->
    <header class="sticky top-0 z-40 border-b border-slate-200 bg-white">
      <nav
        class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-4"
        aria-label="Main"
      >
        <!-- Two links, two destinations. The nav used to carry a `qbiq_h`
             wordmark pointing at `/` as well, immediately beside "Catalogue",
             which pointed at the same place: noise in the nav, a duplicated
             tab stop, and two identical entries in a screen reader's list of
             links. The label that names its destination is the one that
             survived — "Catalogue" says where it goes, which a wordmark only
             implies by convention. -->
        <RouterLink
          to="/"
          class="rounded-sm text-slate-600 hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
        >
          Catalogue
        </RouterLink>
        <RouterLink
          to="/cart"
          class="flex items-center gap-1.5 rounded-sm text-slate-600 hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
        >
          Cart
          <CartBadge />
        </RouterLink>
      </nav>
    </header>
    <main
      id="main-content"
      tabindex="-1"
      class="mx-auto max-w-4xl px-4 py-8 focus:outline-2 focus:outline-offset-4 focus:outline-slate-900"
    >
      <RouterView />
    </main>
  </div>
</template>
