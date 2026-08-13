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
  <div class="min-h-screen bg-cream">
    <!-- Visually hidden until focused: lets a keyboard user jump past the
         repeated header nav straight to the view's content, rather than
         tabbing through "Catalogue" / "Cart" on every page. -->
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-white"
    >
      Skip to main content
    </a>
    <!-- Sticky, because the Cart lives in here. Scrolled down a long
         catalogue, the only route to the Cart was to scroll back to the top,
         and the badge that tells a Shopper what is in it was off-screen for
         most of the page. `z-40` sits under the skip link's `z-50` so a
         focused skip link is never covered by the header it skips. -->
    <header class="sticky top-0 z-40 border-b border-line bg-white">
      <nav
        class="mx-auto flex max-w-4xl items-center gap-6 px-4 py-4"
        aria-label="Main"
      >
        <!-- The mark is deliberately NOT a link. qbiq's own nav puts a
             logo on the left, but this nav's only route to the catalogue is
             the "Catalogue" item beside it — making the mark a second link to
             `/` would restore exactly the duplicate destination that was
             removed: a wasted tab stop and two identical entries in a screen
             reader's list of links. As inert branding it is `aria-hidden`
             artwork plus a wordmark, so assistive tech sees one link to each
             destination and nothing repeated. -->
        <!-- Served from /assets/ rather than the bucket root: that path is the
             behaviour carrying CloudFront's year-long immutable cache policy
             (frontend_stack.py:183), while the default behaviour is
             CACHING_DISABLED and would re-fetch the logo from S3 on every page
             view. Same reasoning as the product thumbnails, and it lives in
             frontend/public/ for the same reason too — anything not in the
             build is deleted by the deploy's `aws s3 sync --delete`.

             `alt="qbiq"` rather than `alt=""`: this is the only thing naming
             the site, so it is content, not decoration. It carries the
             wordmark itself, which is why no text sits beside it. -->
        <img
          src="/assets/qbiq-logo.svg"
          alt="qbiq"
          width="111"
          height="34"
          class="h-8 w-auto select-none"
        >
        <RouterLink
          to="/"
          class="ml-2 rounded-sm text-body hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          Catalogue
        </RouterLink>
        <!-- The Cart is the nav's call to action, styled as the pill qbiq
             uses for one — their `cta small black` — rather than as a third
             text link, so the thing a Shopper acts on does not read as
             navigation. -->
        <RouterLink
          to="/cart"
          class="ml-auto flex items-center gap-1.5 rounded-full bg-ink px-4 py-1.5 text-sm font-medium text-white transition hover:bg-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
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
