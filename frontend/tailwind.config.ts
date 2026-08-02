import type { Config } from 'tailwindcss'
import forms from '@tailwindcss/forms'

/**
 * Design tokens are transcribed from the `DESIGN.md` frontmatter, which is the
 * canonical source (prd.md v0.3.2 / tdd.md §14.3 decisions 12 and 13).
 *
 * Two conflicts inside DESIGN.md were resolved deliberately:
 *
 *  - COLOURS. The prose cites Primary #1A56DB / Secondary #059669 / Tertiary
 *    #7C3AED, none of which match the frontmatter. Those values line up with the
 *    `-container` variants. The frontmatter wins, and it is what all 15 mockups
 *    were generated from.
 *
 *  - RADII. The frontmatter says DEFAULT 0.5rem / md 0.75rem / lg 1rem, while
 *    every mockup declares DEFAULT 0.25rem / lg 0.5rem and styles buttons
 *    `rounded-lg`. The frontmatter scale is used here, so mockup class names
 *    must be REMAPPED rather than copied: a button that was `rounded-lg`
 *    (0.5rem there) becomes `rounded` (0.5rem here). Copying the class name
 *    verbatim would double every control's corner radius.
 *
 * tailwind.config.test.ts pins the values that encode those decisions.
 */
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: '#f8f9ff',
        'surface-dim': '#d1dbec',
        'surface-bright': '#f8f9ff',
        'surface-container-lowest': '#ffffff',
        'surface-container-low': '#eef4ff',
        'surface-container': '#e5eeff',
        'surface-container-high': '#dfe9fa',
        'surface-container-highest': '#d9e3f4',
        'surface-variant': '#d9e3f4',
        'on-surface': '#121c28',
        'on-surface-variant': '#434654',
        'inverse-surface': '#27313e',
        'inverse-on-surface': '#eaf1ff',
        outline: '#737686',
        'outline-variant': '#c3c5d7',
        'surface-tint': '#1353d8',

        primary: '#003fb1',
        'on-primary': '#ffffff',
        'primary-container': '#1a56db',
        'on-primary-container': '#d4dcff',
        'inverse-primary': '#b5c4ff',
        'primary-fixed': '#dbe1ff',
        'primary-fixed-dim': '#b5c4ff',
        'on-primary-fixed': '#00174d',
        'on-primary-fixed-variant': '#003dab',

        secondary: '#006c4a',
        'on-secondary': '#ffffff',
        'secondary-container': '#82f5c1',
        'on-secondary-container': '#00714e',
        'secondary-fixed': '#85f8c4',
        'secondary-fixed-dim': '#68dba9',
        'on-secondary-fixed': '#002114',
        'on-secondary-fixed-variant': '#005137',

        tertiary: '#5d00cc',
        'on-tertiary': '#ffffff',
        'tertiary-container': '#7632e7',
        'on-tertiary-container': '#e5d6ff',
        'tertiary-fixed': '#eaddff',
        'tertiary-fixed-dim': '#d2bbff',
        'on-tertiary-fixed': '#25005a',
        'on-tertiary-fixed-variant': '#5a00c6',

        error: '#ba1a1a',
        'on-error': '#ffffff',
        'error-container': '#ffdad6',
        'on-error-container': '#93000a',

        background: '#f8f9ff',
        'on-background': '#121c28',

        // Role themes and security states (DESIGN.md "Functional Color Logic")
        'student-blue': '#EBF5FF',
        'teacher-indigo': '#4F46E5',
        'status-verified': '#10B981',
        'status-quarantined': '#EF4444',
        'status-pending': '#F59E0B',
        'urdu-accent': '#B91C1C',
        'surface-sandbox': '#F9FAFB',
      },

      // Bound to next/font CSS variables in app/layout.tsx so the faces are
      // self-hosted. The mockups fetched them from fonts.googleapis.com at
      // runtime, which is an extra round trip on mobile data (prd.md A11Y-2).
      fontFamily: {
        headline: ['var(--font-lexend)', 'sans-serif'],
        body: ['var(--font-inter)', 'sans-serif'],
        urdu: ['var(--font-naskh)', 'serif'],
        mono: ['var(--font-jetbrains)', 'monospace'],
      },

      fontSize: {
        /**
         * Display sizes are an EXTENSION, not from the DESIGN.md frontmatter,
         * whose scale tops out at 32px. The landing prototype sets section
         * headings at 48px and the hero larger still; a marketing page needs
         * display type the product type scale does not cover. Extending is the
         * right call here rather than downgrading the design.
         */
        // Measured from the prototype in a browser: h1 and both h2 render at
        // 48px / 56px line-height / -0.96px tracking (= -0.02em).
        'display-md': [
          '48px',
          { lineHeight: '56px', fontWeight: '700', letterSpacing: '-0.02em' },
        ],
        'display-sm': [
          '36px',
          { lineHeight: '42px', fontWeight: '700', letterSpacing: '-0.02em' },
        ],
        'headline-lg': ['32px', { lineHeight: '40px', fontWeight: '700' }],
        'headline-lg-mobile': ['24px', { lineHeight: '32px', fontWeight: '700' }],
        'headline-md': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'body-lg': ['18px', { lineHeight: '28px', fontWeight: '400' }],
        'body-md': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        // Urdu needs 1.8-2.0x line height or diacritics collide (DESIGN.md).
        'urdu-text-lg': ['22px', { lineHeight: '44px', fontWeight: '400' }],
        'urdu-text-md': ['18px', { lineHeight: '36px', fontWeight: '400' }],
        'label-caps': [
          '12px',
          { lineHeight: '16px', letterSpacing: '0.05em', fontWeight: '600' },
        ],
        'code-snippet': ['14px', { lineHeight: '20px', fontWeight: '400' }],
      },

      borderRadius: {
        sm: '0.25rem',
        DEFAULT: '0.5rem',
        md: '0.75rem',
        lg: '1rem',
        xl: '1.5rem',
        full: '9999px',
      },

      spacing: {
        gutter: '24px',
        'margin-mobile': '16px',
        'margin-desktop': '64px',
      },

      maxWidth: {
        'container-max': '1280px',
      },

      // Motion from the prototype. Every one of these is disabled under
      // prefers-reduced-motion in globals.css.
      keyframes: {
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(26, 86, 219, 0.4)' },
          '70%': { boxShadow: '0 0 0 10px rgba(26, 86, 219, 0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(26, 86, 219, 0)' },
        },
        'bob-down': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(6px)' },
        },
        drift: {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '50%': { transform: 'translate3d(0, -14px, 0) scale(1.04)' },
        },
        // Role cards drop in from above, staggered (choose-your-path prototype).
        'roll-down': {
          from: { opacity: '0', transform: 'translateY(-50px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'pulse-ring': 'pulse-ring 2s infinite',
        'bob-down': 'bob-down 2.2s ease-in-out infinite',
        'drift-slow': 'drift 18s ease-in-out infinite',
        'drift-slower': 'drift 26s ease-in-out infinite',
        'roll-down': 'roll-down 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards',
      },

      transitionTimingFunction: {
        // The prototype's easing curves.
        reveal: 'cubic-bezier(0.2, 1, 0.3, 1)',
        lift: 'cubic-bezier(0.16, 1, 0.3, 1)',
        springy: 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
      },
    },
  },
  plugins: [forms],
}

export default config
