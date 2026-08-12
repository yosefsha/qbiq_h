import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'catalogue',
      component: () => import('../components/CataloguePage.vue'),
    },
    {
      path: '/products/:id',
      name: 'product-detail',
      component: () => import('../components/ProductDetailPage.vue'),
      props: true,
    },
    {
      path: '/cart',
      name: 'cart',
      component: () => import('../components/CartPage.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../components/NotFoundPage.vue'),
    },
  ],
})

export default router
