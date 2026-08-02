import { defineRouting } from 'next-intl/routing'

/**
 * WEB LOCALES vs API LANGUAGE VALUES -- these are deliberately not the same.
 *
 * The database enum and the API contract use `roman_ur` (see the applied
 * migration `language_code`). That is a fine internal identifier, but it is
 * NOT a valid BCP-47 language tag: `Intl.NumberFormat('roman_ur')` throws
 * RangeError, and `<html lang="roman_ur">` is invalid, so a screen reader
 * cannot tell what language the page is in.
 *
 * The web layer therefore uses `ur-Latn` -- the correct tag for Urdu written in
 * Latin script -- and maps to `roman_ur` at the API boundary. Both directions
 * live here so the mapping exists in exactly one place.
 */
export const routing = defineRouting({
  locales: ['en', 'ur', 'ur-Latn'],
  defaultLocale: 'en',

  /**
   * English is the default for everyone, always.
   *
   * Left on (the library default), next-intl negotiates from the visitor's
   * `Accept-Language` header and a `NEXT_LOCALE` cookie -- so a browser
   * configured for Urdu, which is entirely normal in this audience, would be
   * redirected to /ur before the visitor had chosen anything. Turning detection
   * off makes `/` resolve to `/en` for every visitor, and language becomes an
   * explicit choice through the switcher.
   *
   * Trade-off, deliberately accepted: this also disables the cookie, so a
   * returning visitor who previously chose Urdu lands on `/` in English again.
   * They stay in Urdu while navigating, because every link carries the locale
   * prefix. Honouring the cookie while still ignoring `Accept-Language` would
   * need custom middleware; next-intl has one flag for both.
   */
  localeDetection: false,
})

export type Locale = (typeof routing.locales)[number]

/** The values the backend and database actually store (`language_code` enum). */
export type ApiLanguage = 'en' | 'ur' | 'roman_ur'

const LOCALE_TO_API: Record<Locale, ApiLanguage> = {
  en: 'en',
  ur: 'ur',
  'ur-Latn': 'roman_ur',
}

const API_TO_LOCALE: Record<ApiLanguage, Locale> = {
  en: 'en',
  ur: 'ur',
  roman_ur: 'ur-Latn',
}

export function toApiLanguage(locale: Locale): ApiLanguage {
  return LOCALE_TO_API[locale]
}

export function fromApiLanguage(language: ApiLanguage): Locale {
  return API_TO_LOCALE[language]
}

/**
 * Urdu script is the ONLY right-to-left locale.
 *
 * Roman-Urdu is Urdu written in Latin script, so it reads left-to-right.
 * Mirroring it would be a defect, not a feature (prd.md I18N-4). This is the
 * single place that decision is encoded -- nothing else should test the locale
 * string to work out direction.
 */
const RTL_LOCALES = new Set<string>(['ur'])

export function isRtl(locale: string): boolean {
  return RTL_LOCALES.has(locale)
}

export function dirFor(locale: string): 'rtl' | 'ltr' {
  return isRtl(locale) ? 'rtl' : 'ltr'
}

/** Endonyms: each language is named in its own script, never translated. */
export const LOCALE_LABELS: Record<Locale, string> = {
  en: 'English',
  ur: 'اردو',
  'ur-Latn': 'Roman Urdu',
}
