import { useTranslations } from 'next-intl'
import { LanguageSwitcher } from '@/components/layout/LanguageSwitcher'
import { Link } from '@/i18n/navigation'

/**
 * The three links under the 2FA card in the prototype, plus the language
 * switcher.
 *
 * The transactional auth screens suppress the site shell, so this is their only
 * footer — and without the switcher here there would be NO way to change
 * language on sign-in, the second factor, or a password reset. That is not an
 * acceptable gap in a product whose premise is Urdu-first (prd.md I18N-1): the
 * screens most likely to be reached from a cold email link are exactly the ones
 * where a user needs their own language.
 *
 * The other targets are the coming-soon page rather than `href="#"`: a dead
 * anchor on a security screen is exactly where a nervous user goes looking for
 * reassurance.
 */
export function AuthFooterLinks() {
  const t = useTranslations('auth.footer')

  const links = [
    { key: 'help', href: '/coming-soon/help' },
    { key: 'privacy', href: '/coming-soon/privacy' },
    { key: 'terms', href: '/coming-soon/terms' },
  ] as const

  return (
    <div className="mt-8 flex flex-col items-center gap-4">
      <LanguageSwitcher />
      <nav className="flex justify-center gap-6 text-body-sm text-on-surface-variant">
        {links.map(({ key, href }) => (
          <Link key={key} href={href} className="transition-colors hover:text-primary">
            {t(key)}
          </Link>
        ))}
      </nav>
    </div>
  )
}
