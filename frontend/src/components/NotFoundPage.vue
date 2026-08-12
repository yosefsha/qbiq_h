<script setup lang="ts">
// Catch-all 404 route. Full error-handling UX (retry, network failure
// messaging, etc.) is built in FE-05 — this is just the placeholder route.
</script>

<template>
  <section class="flex flex-col gap-2">
    <h1 class="text-2xl font-semibold text-slate-900">
      Page not found
    </h1>
    <p class="text-slate-600">
      <RouterLink
        to="/"
        class="text-blue-600 underline"
      >
        Back to the catalogue
      </RouterLink>
    </p>
  </section>
</template>
