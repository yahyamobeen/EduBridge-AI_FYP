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
    setupFiles: ['./vitest.setup.ts'],
    include: ['**/*.test.{ts,tsx}'],
    exclude: ['node_modules/**', '.next/**'],
  },
})
