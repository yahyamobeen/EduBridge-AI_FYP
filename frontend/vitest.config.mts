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
    // ⚠️ RAISED FROM THE 5s DEFAULT BECAUSE THE DEFAULT WAS PRODUCING FALSE
    //    FAILURES, NOT BECAUSE ANYTHING IS SLOW.
    //
    //    The multi-step signup forms drive `userEvent`, which advances real
    //    timers per keystroke. Run alone they finish in well under a second;
    //    run inside the full suite, where several worker threads compete for
    //    CPU, they crossed 5s and failed — `SimpleSignupForm` once, then
    //    `StudentSignupForm` at 5164ms. Both pass 20/20 in isolation, so the
    //    timeout was measuring the machine's load rather than the code.
    //
    //    A flake that only appears in the full run is the worst kind: it
    //    trains everyone to re-run the suite instead of reading it. 15s is
    //    still far below anything a genuinely hung test would reach.
    testTimeout: 15_000,
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
