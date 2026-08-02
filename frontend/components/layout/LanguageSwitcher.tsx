'use client'

import { useLocale, useTranslations } from 'next-intl'
import { Link, usePathname } from '@/i18n/navigation'
import { LOCALE_LABELS, routing } from '@/i18n/routing'

/**
 * A segmented control of real links, not a JS dropdown.
 *
 * Each locale is a genuine URL, so switching works without JavaScript, costs
 * one tap rather than two, and survives a slow connection -- which matters for
 * the entry-level Android audience in prd.md 3.1. DESIGN.md also asks for a
 * prominent switcher rather than something buried in a menu.
 *
 * `usePathname` here is the locale-aware one: it returns the path WITHOUT the
 * locale prefix, so the same page is preserved when switching.
 */
export function LanguageSwitcher() {
  const t = useTranslations('languageSwitcher')
  const pathname = usePathname()
  const activeLocale = useLocale()

  return (
    <nav aria-label={t('label')}>
      <ul className="flex items-center gap-0 overflow-hidden rounded border border-outline-variant">
        {routing.locales.map((locale) => {
          const isActive = locale === activeLocale
          return (
            <li key={locale}>
              <Link
                href={pathname}
                locale={locale}
                aria-current={isActive ? 'true' : undefined}
                // Urdu needs the Naskh face even in an English page's switcher,
                // or the endonym renders in a fallback that mangles the script.
                lang={locale === 'ur' ? 'ur' : undefined}
                className={
                  isActive
                    ? 'block bg-primary px-3 py-2 text-body-sm font-semibold text-on-primary'
                    : 'block px-3 py-2 text-body-sm text-on-surface-variant hover:bg-surface-container-high'
                }
              >
                {LOCALE_LABELS[locale]}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
