import { useTranslations } from 'next-intl'

/**
 * Keyboard users must be able to jump past the navigation (prd.md A11Y-1).
 * Visually hidden until focused, then pinned to the inline-start edge so it
 * lands on the correct side in both directions.
 */
export function SkipLink() {
  const t = useTranslations('a11y')

  return (
    <a
      href="#main"
      className="sr-only rounded bg-primary px-4 py-2 text-body-sm text-on-primary focus-visible:not-sr-only focus-visible:absolute focus-visible:start-4 focus-visible:top-4 focus-visible:z-50"
    >
      {t('skipToContent')}
    </a>
  )
}
