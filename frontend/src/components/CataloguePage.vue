<script setup lang="ts">
/**
 * Browse, filter, and sort the catalogue. All narrowing happens server-side
 * (see `stores/catalogue.ts`) — this component only ever renders the page
 * the API returned for the current query.
 *
 * The query is kept in sync with the URL in both directions:
 *  - on mount, and on browser back/forward, the URL is parsed into a query
 *    and pushed into the store;
 *  - whenever the store's query changes (typing, a filter, a page turn), the
 *    URL is updated to match via `router.replace` (no new history entry per
 *    keystroke).
 *
 * Both watchers compare against `parseCatalogueQuery(route.query)` rather
 * than the two sides' raw values, so once they agree the comparison is
 * false and the loop stops there: the URL-driven watcher applying a query
 * that already matches the store is a no-op, and the store-driven watcher
 * replacing a URL that already matches the store is skipped before
 * `router.replace` is ever called.
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  parseCatalogueQuery,
  toRouteQuery,
  type CatalogueQuery,
  type ProductSortField,
  type SortDirection,
} from '../catalogueQuery'
import { useCatalogueStore } from '../stores/catalogue'
import { debounce } from '../debounce'
import ErrorState from './ErrorState.vue'
import ProductCard from './ProductCard.vue'

interface SortOption {
  value: string
  sort: ProductSortField | undefined
  direction: SortDirection | undefined
  label: string
}

const SORT_OPTIONS: SortOption[] = [
  { value: '', sort: undefined, direction: undefined, label: 'Default order' },
  { value: 'name-asc', sort: 'name', direction: 'asc', label: 'Name (A–Z)' },
  { value: 'name-desc', sort: 'name', direction: 'desc', label: 'Name (Z–A)' },
  { value: 'price-asc', sort: 'price', direction: 'asc', label: 'Price (low to high)' },
  { value: 'price-desc', sort: 'price', direction: 'desc', label: 'Price (high to low)' },
]

const NAME_FILTER_DEBOUNCE_MS = 300

const route = useRoute()
const router = useRouter()
const store = useCatalogueStore()

const nameInput = ref(store.query.name)

const debouncedNameChange = debounce((value: string) => {
  void store.updateQuery({ name: value })
}, NAME_FILTER_DEBOUNCE_MS)

function onNameInput(): void {
  debouncedNameChange.run(nameInput.value)
}

const sortValue = computed<string>(() => {
  const match = SORT_OPTIONS.find(
    (option) => option.sort === store.query.sort && option.direction === store.query.direction,
  )
  return match?.value ?? ''
})

function onSortChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const option = SORT_OPTIONS.find((candidate) => candidate.value === value)
  void store.updateQuery({ sort: option?.sort, direction: option?.direction })
}

function onCategoryChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  void store.updateQuery({ category: value || undefined })
}

const currentPage = computed(() => Math.floor(store.query.offset / store.query.limit) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(store.total / store.query.limit)))
const canGoPrevious = computed(() => store.query.offset > 0)
const canGoNext = computed(() => store.query.offset + store.query.limit < store.total)

function goToPreviousPage(): void {
  if (!canGoPrevious.value) return
  void store.updateQuery({ offset: Math.max(0, store.query.offset - store.query.limit) })
}

function goToNextPage(): void {
  if (!canGoNext.value) return
  void store.updateQuery({ offset: store.query.offset + store.query.limit })
}

/**
 * A single polite live region announcing "N products found"/"no products
 * found"/"loading" for screen-reader users, who otherwise get no signal that
 * a filter or page change silently swapped the list below. Deliberately
 * empty while `store.error` is set: `ErrorState` already renders with
 * `role="alert"`, so pairing that with a second, differently-worded
 * announcement here would just talk over it.
 */
const resultsAnnouncement = computed<string>(() => {
  if (store.error) return ''
  if (store.loading) return 'Loading products…'
  if (store.total === 0) return 'No products found.'
  return `${store.total} product${store.total === 1 ? '' : 's'} found.`
})

// --- URL <-> store sync -----------------------------------------------

function applyRouteQuery(query: CatalogueQuery): void {
  nameInput.value = query.name
  void store.setQuery(query)
}

watch(
  () => parseCatalogueQuery(route.query),
  (parsed, previous) => {
    if (previous !== undefined && JSON.stringify(parsed) === JSON.stringify(store.query)) {
      return
    }
    applyRouteQuery(parsed)
  },
  { immediate: true },
)

watch(
  () => store.query,
  (query) => {
    const parsedFromRoute = parseCatalogueQuery(route.query)
    if (JSON.stringify(query) === JSON.stringify(parsedFromRoute)) {
      return
    }
    void router.replace({ query: toRouteQuery(query) })
  },
)

void store.fetchCategories()

onUnmounted(() => {
  debouncedNameChange.cancel()
})
</script>

<template>
  <section class="flex flex-col gap-6">
    <div class="flex flex-col gap-2">
      <h1 class="text-2xl font-semibold text-slate-900">
        Catalog
      </h1>
      <p class="text-slate-600">
        Browse the full range of digital products.
      </p>
    </div>

    <p
      aria-live="polite"
      class="sr-only"
    >
      {{ resultsAnnouncement }}
    </p>

    <form
      class="flex flex-wrap items-end gap-4"
      @submit.prevent
    >
      <div class="flex flex-col gap-1">
        <label
          for="catalogue-name-filter"
          class="text-sm font-medium text-slate-700"
        >Search</label>
        <input
          id="catalogue-name-filter"
          v-model="nameInput"
          type="search"
          placeholder="Search by name"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          @input="onNameInput"
        >
      </div>

      <div class="flex flex-col gap-1">
        <label
          for="catalogue-category-filter"
          class="text-sm font-medium text-slate-700"
        >Category</label>
        <select
          id="catalogue-category-filter"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          :value="store.query.category ?? ''"
          @change="onCategoryChange"
        >
          <option value="">
            All categories
          </option>
          <option
            v-for="category in store.categories"
            :key="category.slug"
            :value="category.slug"
          >
            {{ category.name }}
          </option>
        </select>
      </div>

      <div class="flex flex-col gap-1">
        <label
          for="catalogue-sort"
          class="text-sm font-medium text-slate-700"
        >Sort by</label>
        <select
          id="catalogue-sort"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          :value="sortValue"
          @change="onSortChange"
        >
          <option
            v-for="option in SORT_OPTIONS"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </div>
    </form>

    <ErrorState
      v-if="store.error"
      :error="store.error"
      @retry="store.fetchProducts"
    />

    <div
      v-else-if="store.loading"
      class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="catalogue-skeleton"
      aria-busy="true"
      aria-label="Loading products"
    >
      <div
        v-for="n in store.query.limit"
        :key="n"
        class="flex animate-pulse flex-col overflow-hidden rounded-lg border border-slate-200 bg-white"
      >
        <div class="aspect-video w-full bg-slate-200" />
        <div class="flex flex-1 flex-col gap-2 p-4">
          <div class="h-3 w-1/3 rounded bg-slate-200" />
          <div class="h-4 w-3/4 rounded bg-slate-200" />
          <div class="h-3 w-full rounded bg-slate-200" />
          <div class="h-4 w-1/4 rounded bg-slate-200" />
        </div>
      </div>
    </div>

    <div
      v-else-if="store.items.length === 0"
      class="flex flex-col items-start gap-2 rounded-lg border border-slate-200 bg-white p-6"
      data-testid="catalogue-empty"
    >
      <h2 class="font-semibold text-slate-900">
        No products found
      </h2>
      <p class="text-sm text-slate-600">
        Try a different search term or category.
      </p>
    </div>

    <template v-else>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ProductCard
          v-for="product in store.items"
          :key="product.id"
          :product="product"
        />
      </div>

      <div class="flex items-center justify-between">
        <button
          type="button"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canGoPrevious"
          @click="goToPreviousPage"
        >
          Previous
        </button>
        <span class="text-sm text-slate-600">
          Page {{ currentPage }} of {{ totalPages }} ({{ store.total }} products)
        </span>
        <button
          type="button"
          class="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canGoNext"
          @click="goToNextPage"
        >
          Next
        </button>
      </div>
    </template>
  </section>
</template>
