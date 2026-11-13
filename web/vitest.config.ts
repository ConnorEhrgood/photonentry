import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  // Test files are kept out of tsconfig.app.json (the production build), so say how to compile JSX here.
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    // Coverage is a ratchet (as in PhotonConsole): raise these, never lower them to pass a change.
    coverage: {
      include: ['src/**'],
      exclude: ['src/main.tsx', 'src/test/**', 'src/**/*.test.{ts,tsx}', 'src/vite-env.d.ts'],
      thresholds: { lines: 97, functions: 92, branches: 82, statements: 94 },   // PhotonEntry's starting point (2026-11-13)
    },
  },
})
