import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

/**
 * The three links under the 2FA card in the prototype.
 *
 * The transactional auth screens suppress the site shell, so this is their only
 * footer. The targets are the coming-soon page rather than `href="#"`: a dead
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
    <nav className="mt-8 flex justify-center gap-6 text-body-sm text-on-surface-variant">
      {links.map(({ key, href }) => (
        <Link key={key} href={href} className="transition-colors hover:text-primary">
          {t(key)}
        </Link>
      ))}
    </nav>
  )
}
