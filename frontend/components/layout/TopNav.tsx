import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { LanguageSwitcher } from './LanguageSwitcher'

/**
 * The prototype's sticky translucent nav, including its four section links
 * with the underline that grows on hover.
 *
 * Curriculum, Tutor and Progress are authenticated product areas that do not
 * exist yet, so they point at the coming-soon page rather than nowhere.
 * Solutions is a real in-page anchor.
 */
const SECTION_LINKS = [
  { key: 'curriculum', href: '/coming-soon/curriculum' },
  { key: 'tutor', href: '/coming-soon/tutor' },
  { key: 'progress', href: '/coming-soon/progress' },
] as const

export function TopNav() {
  const t = useTranslations('nav')
  const tApp = useTranslations('app')

  const underline =
    'absolute bottom-0 start-0 h-0.5 w-0 bg-primary transition-all duration-300 group-hover:w-full'

  return (
    <header className="sticky top-0 z-40 border-b border-outline-variant/40 bg-surface/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-container-max items-center justify-between gap-4 px-gutter py-4">
        <Link
          href="/"
          className="font-headline text-headline-md text-primary transition-opacity hover:opacity-80"
        >
          {tApp('name')}
        </Link>

        <nav className="hidden items-center gap-8 md:flex" aria-label={tApp('name')}>
          <a
            href="#solutions"
            className="group relative py-1 text-body-sm font-semibold text-on-surface-variant transition-colors hover:text-primary"
          >
            {t('solutions')}
            <span className={underline} />
          </a>
          {SECTION_LINKS.map(({ key, href }) => (
            <Link
              key={key}
              href={href}
              className="group relative py-1 text-body-sm font-semibold text-on-surface-variant transition-colors hover:text-primary"
            >
              {t(key)}
              <span className={underline} />
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          <LanguageSwitcher />
          <Link
            href="/login"
            className="hidden px-2 py-2 text-body-sm font-semibold text-on-surface-variant transition-colors hover:text-primary sm:block"
          >
            {t('signIn')}
          </Link>
          <Link
            href="/signup"
            className="rounded bg-primary-container px-4 py-2 text-body-sm font-semibold text-on-primary transition-colors hover:bg-primary"
          >
            {t('signUp')}
          </Link>
        </div>
      </div>
    </header>
  )
}
