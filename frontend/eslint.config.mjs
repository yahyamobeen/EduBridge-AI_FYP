import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'
import nextTypescript from 'eslint-config-next/typescript'

// `next lint` was removed in Next 16, so ESLint runs directly.
// eslint-config-next 16 exports flat-config arrays, so no FlatCompat shim.
const config = [
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'coverage/**'] },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // RTL correctness (prd.md I18N-4) is enforced by review and the Phase 12
      // sweep, not by ESLint -- there is no rule that understands Tailwind
      // class strings. Kept as a note so nobody assumes lint covers it.
    },
  },
]

export default config
