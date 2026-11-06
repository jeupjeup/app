import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  server: { host: '127.0.0.1', port: 5177, strictPort: true, proxy: Object.fromEntries(['/api', '/v1', '/healthz'].map(path => [path, { target: process.env.JUPJUP_API_ORIGIN || 'http://127.0.0.1:8000' }])) },
  preview: { host: '127.0.0.1', port: 5178, strictPort: true },
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
