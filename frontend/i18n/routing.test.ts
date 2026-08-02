import { describe, expect, it } from 'vitest'
import {
  dirFor,
  fromApiLanguage,
  isRtl,
  LOCALE_LABELS,
  routing,
  toApiLanguage,
  type ApiLanguage,
  type Locale,
} from './routing'

describe('default locale', () => {
  it('is English', () => {
    expect(routing.defaultLocale).toBe('en')
  })

  it('does not negotiate the locale from the browser', () => {
    // With detection on, a browser set to Urdu is redirected to /ur before the
    // visitor chooses anything. English is the default for everyone; language
    // is picked explicitly through the switcher.
    expect(routing.localeDetection).toBe(false)
  })
})

describe('locale tags', () => {
  /**
   * This is the regression guard for a real defect: the contract's `roman_ur`
   * was used as a web locale, and it is not a valid BCP-47 tag. `Intl` throws
   * RangeError on it and `<html lang="roman_ur">` is invalid, so assistive
   * technology cannot identify the page language. `ur-Latn` is the correct tag.
   */
  it('every routing locale is a valid BCP-47 tag', () => {
    for (const locale of routing.locales) {
      expect(() => Intl.getCanonicalLocales(locale), `${locale} must be valid`).not.toThrow()
      expect(
        () => new Intl.NumberFormat(locale).format(1),
        `${locale} formatting`,
      ).not.toThrow()
    }
  })

  it('has a label for every locale, written in its own script', () => {
    for (const locale of routing.locales) {
      expect(LOCALE_LABELS[locale]).toBeTruthy()
    }
    expect(LOCALE_LABELS.ur).toBe('اردو')
  })
})

describe('text direction', () => {
  it('treats Urdu script as the only RTL locale', () => {
    expect(isRtl('ur')).toBe(true)
    expect(dirFor('ur')).toBe('rtl')
  })

  it('keeps Roman-Urdu left-to-right because it is Latin script', () => {
    // Mirroring ur-Latn would be a defect, not a feature (prd.md I18N-4).
    expect(isRtl('ur-Latn')).toBe(false)
    expect(dirFor('ur-Latn')).toBe('ltr')
  })

  it('keeps English left-to-right', () => {
    expect(isRtl('en')).toBe(false)
    expect(dirFor('en')).toBe('ltr')
  })

  it('does not treat an unknown locale as RTL', () => {
    expect(isRtl('xx')).toBe(false)
  })
})

describe('API language mapping', () => {
  it('maps the web locale to the language_code enum the database stores', () => {
    expect(toApiLanguage('en')).toBe('en')
    expect(toApiLanguage('ur')).toBe('ur')
    expect(toApiLanguage('ur-Latn')).toBe('roman_ur')
  })

  it('round-trips in both directions for every locale', () => {
    for (const locale of routing.locales) {
      expect(fromApiLanguage(toApiLanguage(locale))).toBe(locale)
    }
  })

  it('round-trips every API language value', () => {
    const languages: ApiLanguage[] = ['en', 'ur', 'roman_ur']
    for (const language of languages) {
      expect(toApiLanguage(fromApiLanguage(language))).toBe(language)
    }
  })

  it('covers every routing locale, so a new locale cannot be added silently', () => {
    const mapped = routing.locales.map((locale: Locale) => toApiLanguage(locale))
    expect(new Set(mapped).size).toBe(routing.locales.length)
  })
})
