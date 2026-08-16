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
    // `NEXT_PUBLIC_API_MODE: 'live'` used to be pinned here, because the mock
    // layer defaulted ON outside production and would have swallowed the client
    // tests' stubbed fetch. The mock layer is gone, so the pin is too.
    env: {
      NEXT_PUBLIC_TURNSTILE_SITE_KEY: '0x-test-site-key',
    },
    setupFiles: ['./vitest.setup.ts'],
    include: ['**/*.test.{ts,tsx}'],
    exclude: ['node_modules/**', '.next/**'],
    // `proxy.test.ts` loads `next-intl/middleware`, whose ESM build imports the
    // extensionless specifier `next/server`. Left external, Node's own loader
    // resolves that import and fails -- `next` publishes no `exports` map, so
    // the bare specifier only resolves through a bundler. Inlining hands it to
    // Vite, which does resolve it. The component tests are unaffected: they
    // import `next-intl` itself, not the middleware entry point.
    server: { deps: { inline: ['next-intl'] } },
  },
})
