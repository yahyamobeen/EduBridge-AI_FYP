'use client'

import { useEffect } from 'react'
import { useTranslations } from 'next-intl'

/**
 * The last line of defence: an uncaught render error anywhere under this
 * locale.
 *
 * It renders no site chrome and imports nothing beyond translations, because
 * whatever just failed may be exactly what the chrome depends on — an error
 * boundary that itself throws leaves the framework's untranslated grey page,
 * which is worse than no boundary at all.
 *
 * The error is deliberately NOT shown. A stack or a message from a failed
 * request can carry an email address, a token fragment or an internal path, and
 * this page is reachable by anyone. It is logged to the console for a developer
 * and summarised for the user.
 */
export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const t = useTranslations('errorPage')

  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <main id="main" className="flex flex-1 items-center justify-center px-gutter py-24">
      <div className="w-full max-w-md text-center">
        <h1 className="mb-3 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
          {t('title')}
        </h1>
        <p className="mb-8 text-body-md text-on-surface-variant">{t('body')}</p>

        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={reset}
            className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary transition-colors hover:bg-primary-container"
          >
            {t('retry')}
          </button>
          {/*
            A plain anchor with a full page load, NOT the locale-aware Link. The
            router is a plausible cause of whatever just threw, so the way out
            must not depend on it — a client-side navigation could land the user
            straight back in the broken tree. eslint wants Link here; a hard
            navigation is the point.
          */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/" className="text-body-sm text-primary hover:text-primary-container">
            {t('home')}
          </a>
        </div>

        {/* Useful in a bug report, meaningless to an attacker. */}
        {error.digest && (
          <p className="force-ltr mt-8 font-mono text-body-sm text-outline">
            {t('reference', { digest: error.digest })}
          </p>
        )}
      </div>
    </main>
  )
}
