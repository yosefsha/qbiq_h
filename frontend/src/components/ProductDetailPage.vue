<script setup lang="ts">
// Placeholder for the product detail view. The real product detail, reviews
// list, and "Add to Cart" behaviour are built in FE-03.
interface Props {
  id: string
}

const props = defineProps<Props>()
</script>

<template>
  <section class="flex flex-col gap-2">
    <h1 class="text-2xl font-semibold text-slate-900">
      Product detail
    </h1>
    <p class="text-slate-600">
      Details for product <span class="font-mono">{{ props.id }}</span> will render here.
    </p>
  </section>
</template>
