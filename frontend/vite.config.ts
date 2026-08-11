/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // The default forked-process pool times out spawning workers in this sandboxed
    // dev environment; the thread-based pool runs in-process and works reliably here.
    pool: 'threads',
  },
})
