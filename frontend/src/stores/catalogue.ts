/**
 * The catalogue: the current page of `Product`s for a `CatalogueQuery`, and
 * the list of `Category`s used to populate the filter UI.
 *
 * All filtering, sorting, and paging happens server-side — this store only
 * ever renders exactly the `items`/`total` the API returned for the query it
 * sent. There is no `.filter()`/`.sort()` here or in `CataloguePage.vue`; if
 * the list needs to look different, that's a new `?query` param, not local
 * array surgery.
 *
 * Built on `useAsyncRequest` rather than a hand-rolled request/token guard:
 * each `execute()` call reads `query`/`categoryQuery` at call time (they're
 * plain closures, not bound to a snapshot), and `useAsyncRequest`'s existing
 * token guard already discards a superseded response — e.g. a slow request
 * for an earlier name filter landing after a faster, newer one — so a
 * second guard here would be redundant.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { apiClient } from '../api/client'
import { buildProductsSearchParams, DEFAULT_CATALOGUE_QUERY } from '../catalogueQuery'
import type { CatalogueQuery } from '../catalogueQuery'
import { useAsyncRequest } from '../composables/useAsyncRequest'
import type { ApiError, Category, ProductPage } from '../types'

export const useCatalogueStore = defineStore('catalogue', () => {
  const query = ref<CatalogueQuery>({ ...DEFAULT_CATALOGUE_QUERY })

  const {
    status: productsStatus,
    data: productsPage,
    error: productsError,
    execute: executeProducts,
  } = useAsyncRequest<ProductPage>(
    () => apiClient.get<ProductPage>(`/products?${buildProductsSearchParams(query.value)}`),
    { immediate: false },
  )

  const {
    status: categoriesStatus,
    data: categoriesData,
    error: categoriesError,
    execute: executeCategories,
  } = useAsyncRequest<Category[]>(() => apiClient.get<Category[]>('/categories'), {
    immediate: false,
  })

  const items = computed(() => productsPage.value?.items ?? [])
  const total = computed(() => productsPage.value?.total ?? 0)
  const loading = computed(() => productsStatus.value === 'loading')
  const error = computed<ApiError | undefined>(() => productsError.value)

  const categories = computed(() => categoriesData.value ?? [])
  const categoriesLoading = computed(() => categoriesStatus.value === 'loading')

  /** Issues a request for the current `query` as-is. Used for the initial load and for "Retry". */
  function fetchProducts(): Promise<void> {
    return executeProducts()
  }

  /** Loads the category list for the filter UI. Safe to call more than once (e.g. on retry). */
  function fetchCategories(): Promise<void> {
    return executeCategories()
  }

  /**
   * Replaces `query` wholesale and fetches it — used to restore a query read
   * straight from the URL, where `offset` must be taken as given rather than
   * reset to 0.
   */
  function setQuery(next: CatalogueQuery): Promise<void> {
    query.value = next
    return fetchProducts()
  }

  /**
   * Applies a partial change to `query` and fetches the result. Changing a
   * filter or sort implicitly returns to the first page, since the previous
   * `offset` may no longer point at a meaningful page of the new result set;
   * an explicit `offset` in `patch` (paging forward/back) is respected as-is.
   */
  function updateQuery(patch: Partial<CatalogueQuery>): Promise<void> {
    const offset = patch.offset ?? (Object.keys(patch).length > 0 ? 0 : query.value.offset)
    query.value = { ...query.value, ...patch, offset }
    return fetchProducts()
  }

  return {
    query,
    items,
    total,
    loading,
    error,
    categories,
    categoriesLoading,
    categoriesError,
    fetchProducts,
    fetchCategories,
    setQuery,
    updateQuery,
  }
})
