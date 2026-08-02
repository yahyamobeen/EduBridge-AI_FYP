import { useTranslations } from 'next-intl'
import { Footer } from '@/components/layout/Footer'
import { TopNav } from '@/components/layout/TopNav'
import { Link } from '@/i18n/navigation'

/**
 * Localized 404. Brought forward from the hardening phase because the landing
 * page links to /signup and /login, which arrive in later phases -- an
 * untranslated framework error page would be a poor answer in the meantime.
 *
 * It renders its own shell. `not-found.tsx` sits beside the locale layout, so
 * it is outside both the (site) and (auth) groups and inherits neither -- and a
 * dead end is the one page that most needs a way back out.
 */
export default function NotFound() {
  const t = useTranslations('notFound')

  return (
    <>
      <TopNav />
      <main id="main" className="flex-1">
        <div className="mx-auto max-w-container-max px-margin-mobile py-24 md:px-margin-desktop">
          <h1 className="font-headline text-headline-lg-mobile md:text-headline-lg">
            {t('title')}
          </h1>
          <p className="mt-4 max-w-prose text-body-md text-on-surface-variant">{t('body')}</p>
          <Link
            href="/"
            className="mt-8 inline-block rounded bg-primary px-5 py-3 text-body-md font-semibold text-on-primary"
          >
            {t('cta')}
          </Link>
        </div>
      </main>
      <Footer />
    </>
  )
}
