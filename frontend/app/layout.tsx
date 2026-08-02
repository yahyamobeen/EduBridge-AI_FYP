import type { Metadata, Viewport } from 'next'
import { fontVariables } from './fonts'
import './globals.css'

export const metadata: Metadata = {
  title: 'EduBridge AI',
  description:
    'Curriculum-grounded AI tutoring for Classes 9-12, aligned to the Punjab (PCTB) and Sindh (STBB) boards.',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

/**
 * Phase 1 root layout. Phase 2 introduces the `[locale]` segment, which takes
 * over `lang` and `dir` -- both are hardcoded here only until then.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" className={fontVariables}>
      <body>{children}</body>
    </html>
  )
}
