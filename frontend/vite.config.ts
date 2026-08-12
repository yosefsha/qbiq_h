/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// In the dev profile the SPA and API are on different origins, so Vite proxies
// /api to the API. This keeps the browser talking to a single origin, which is
// what allows the session cookie to stay SameSite=Lax (ADR-001) in development
// exactly as it does behind nginx and CloudFront.
// Defaults to the host-published API port; the Compose dev profile overrides it
// with the service name.
const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': { target: devProxyTarget, changeOrigin: false },
      '/health': { target: devProxyTarget, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.ts'],
  },
})
