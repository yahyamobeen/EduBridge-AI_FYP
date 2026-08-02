import { Inter, JetBrains_Mono, Lexend, Noto_Naskh_Arabic } from 'next/font/google'

/**
 * Self-hosted through next/font (prd.md A11Y-2). The mockups linked
 * fonts.googleapis.com at runtime, which costs an extra round trip on mobile
 * data and adds a third-party dependency to first paint.
 *
 * All four are variable fonts, so no `weight` is declared -- next/font would
 * reject an explicit weight list for a variable face.
 */

export const lexend = Lexend({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-lexend',
})

export const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
})

export const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains',
})

/** Urdu script only. Loaded for every locale today; Phase 2 scopes it to `ur`. */
export const notoNaskhArabic = Noto_Naskh_Arabic({
  subsets: ['arabic'],
  display: 'swap',
  variable: '--font-naskh',
})

export const fontVariables = [
  lexend.variable,
  inter.variable,
  jetbrainsMono.variable,
  notoNaskhArabic.variable,
].join(' ')
