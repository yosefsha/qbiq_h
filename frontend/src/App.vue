<script setup lang="ts">
// Root component: layout shell only. Feature views own their own content.
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
          class="text-slate-600 hover:text-slate-900"
        >
          Cart
        </RouterLink>
      </nav>
    </header>
    <main class="mx-auto max-w-4xl px-4 py-8">
      <RouterView />
    </main>
  </div>
</template>
