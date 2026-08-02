import { Inter, JetBrains_Mono, Lexend, Noto_Naskh_Arabic } from 'next/font/google'
import { isRtl } from '@/i18n/routing'

/**
 * Self-hosted through next/font (prd.md A11Y-2). The mockups linked
 * fonts.googleapis.com at runtime, which costs an extra round trip on mobile
 * data and adds a third-party dependency to first paint.
 *
 * All four are variable fonts, so no `weight` is declared -- next/font rejects
 * an explicit weight list for a variable face.
 */

const lexend = Lexend({ subsets: ['latin'], display: 'swap', variable: '--font-lexend' })
const inter = Inter({ subsets: ['latin'], display: 'swap', variable: '--font-inter' })
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains',
})

/**
 * Urdu script face. `preload: false` and conditional application mean an
 * English or Roman-Urdu visitor never downloads it -- a Naskh face is a large
 * asset to push at a student on metered mobile data who cannot read it.
 */
const notoNaskhArabic = Noto_Naskh_Arabic({
  subsets: ['arabic'],
  display: 'swap',
  variable: '--font-naskh',
  preload: false,
})

const latinVariables = [lexend.variable, inter.variable, jetbrainsMono.variable].join(' ')

/** Font CSS variables for a locale. Urdu additionally gets the Naskh face. */
export function fontVariablesFor(locale: string): string {
  return isRtl(locale) ? `${latinVariables} ${notoNaskhArabic.variable}` : latinVariables
}
