import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
  },
  {
    name: 'app/files-to-ignore',
    ignores: ['**/dist/**', '**/dist-ssr/**', '**/coverage/**', '**/node_modules/**'],
  },
  // eslint-plugin-vue v10's "recommended" flat config is the Vue 3 recommended
  // ruleset — the "vue3-" prefix from the legacy (non-flat) config names is
  // dropped now that Vue 3 is the default target.
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  {
    name: 'app/rules',
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    name: 'app/no-direct-fetch',
    files: ['src/**/*.{ts,vue}'],
    ignores: ['src/api/client.ts'],
    rules: {
      'no-restricted-globals': [
        'error',
        {
          name: 'fetch',
          message: 'Import apiClient from src/api/client.ts instead of calling fetch directly.',
        },
      ],
      'no-restricted-properties': [
        'error',
        {
          object: 'window',
          property: 'fetch',
          message: 'Import apiClient from src/api/client.ts instead of calling fetch directly.',
        },
      ],
    },
  },
)
