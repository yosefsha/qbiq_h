<script setup lang="ts">
// Catch-all 404 route for any URL that doesn't match a known route
// (see router/index.ts's `/:pathMatch(.*)*`). Distinct from ErrorState,
// which presents a failed API call — this page is about an unmatched
// client-side route.
</script>

<template>
  <section class="flex flex-col items-start gap-3">
    <p class="text-sm font-semibold tracking-wide text-slate-500 uppercase">
      404
    </p>
    <h1 class="text-2xl font-semibold text-slate-900">
      Page not found
    </h1>
    <p class="text-slate-600">
      There's nothing here. The page you're looking for may have been moved or never existed.
    </p>
    <RouterLink
      to="/"
      class="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
    >
      Back to the catalogue
    </RouterLink>
  </section>
</template>
