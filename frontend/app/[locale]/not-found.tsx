import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

/**
 * Localized 404. Brought forward from the hardening phase because the landing
 * page links to /signup and /login, which arrive in later phases -- an
 * untranslated framework error page would be a poor answer in the meantime.
 */
export default function NotFound() {
  const t = useTranslations('notFound')

  return (
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
  )
}
