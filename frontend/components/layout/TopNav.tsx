import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { LanguageSwitcher } from './LanguageSwitcher'

/**
 * Sign-in and sign-up are placeholders until Phases 5 and 6 build those routes;
 * they point at the paths those phases will create rather than at `#`, so no
 * dead links ship (the supplied mockups used `href="#"` throughout).
 */
export function TopNav() {
  const t = useTranslations('nav')
  const tApp = useTranslations('app')

  return (
    <header className="border-b border-outline-variant bg-surface-container-lowest">
      <div className="mx-auto flex max-w-container-max flex-wrap items-center justify-between gap-3 px-margin-mobile py-3 md:px-margin-desktop">
        <Link
          href="/"
          className="font-headline text-headline-md text-primary"
          aria-label={tApp('name')}
        >
          {tApp('name')}
        </Link>

        <div className="flex items-center gap-3">
          <LanguageSwitcher />
          <Link
            href="/login"
            className="px-2 py-2 text-body-sm font-semibold text-on-surface-variant hover:text-primary"
          >
            {t('signIn')}
          </Link>
          <Link
            href="/signup"
            className="rounded bg-primary px-4 py-2 text-body-sm font-semibold text-on-primary"
          >
            {t('signUp')}
          </Link>
        </div>
      </div>
    </header>
  )
}
