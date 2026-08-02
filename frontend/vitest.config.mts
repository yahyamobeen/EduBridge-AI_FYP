import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// .mts so Vite's native config loader reads it as ESM.
// tsconfig `paths` are resolved by Vite directly -- no vite-tsconfig-paths.
export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: 'jsdom',
    globals: true,
    // The client tests stub fetch to exercise the real transport: refresh,
    // retry and the 403 redirects. Without pinning this they would fall
    // through to the mock layer, which defaults on outside production.
    env: { NEXT_PUBLIC_API_MODE: 'live' },
    setupFiles: ['./vitest.setup.ts'],
    include: ['**/*.test.{ts,tsx}'],
    exclude: ['node_modules/**', '.next/**'],
  },
})
