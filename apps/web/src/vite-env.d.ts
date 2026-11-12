/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_AUTH_MODE?: 'local' | 'supabase'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
