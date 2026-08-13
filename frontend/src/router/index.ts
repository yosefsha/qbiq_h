import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'catalogue',
      component: () => import('../components/CataloguePage.vue'),
      meta: { title: 'Catalog' },
    },
    {
      path: '/products/:id',
      name: 'product-detail',
      component: () => import('../components/ProductDetailPage.vue'),
      props: true,
      meta: { title: 'Product' },
    },
    {
      path: '/cart',
      name: 'cart',
      component: () => import('../components/CartPage.vue'),
      meta: { title: 'Cart' },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../components/NotFoundPage.vue'),
      meta: { title: 'Page not found' },
    },
  ],
})

/**
 * Moves focus to the app's `<main>` landmark after every navigation, and
 * updates `document.title` to match.
 *
 * An SPA route change doesn't reload the document, so without this a
 * keyboard/screen-reader user's focus is left stranded on whatever element
 * they just activated in the *previous* view (a link that may no longer
 * exist), and nothing announces that the view actually changed.
 *
 * The more precise target would be each view's own `<h1>`, but that isn't
 * timing-safe here: every route's component is an async `() => import(...)`
 * chunk, and `ProductDetailPage` additionally fetches its data after mount
 * and has no heading at all while that request is in flight (see its
 * `status === 'loading'` branch) — `afterEach` can fire before either has
 * produced a heading to focus. `<main id="main-content">` (App.vue) is,
 * by contrast, always present in the DOM, so focusing it is a timing-safe
 * "skip target": it puts assistive tech on the new view's landmark
 * immediately, with that view's actual heading the very next thing read.
 * `requestAnimationFrame` gives the outgoing view a paint cycle to unmount
 * and the incoming one (including its async chunk, once resolved) a chance
 * to have committed before focus moves.
 */
router.afterEach((to) => {
  if (typeof to.meta.title === 'string') {
    document.title = `${to.meta.title} · qbiq_h`
  }
  requestAnimationFrame(() => {
    document.getElementById('main-content')?.focus()
  })
})

export default router
