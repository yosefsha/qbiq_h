/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL the API client prefixes onto every request path. */
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
