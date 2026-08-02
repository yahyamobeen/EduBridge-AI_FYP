import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

/**
 * The prototype's footer, measured: surface-variant background, 64px vertical
 * padding, brand and tagline beside four links, copyright underneath.
 *
 * "Institutional Access" is kept from the prototype and points at the
 * coming-soon page — prd.md §15 CL-6 has institutions attach through classroom
 * join codes, with no institutional route in v1.
 */
export function Footer() {
  const t = useTranslations('footer')
  const tApp = useTranslations('app')

  const links = [
    { key: 'integrity', href: '/coming-soon/integrity' },
    { key: 'privacy', href: '/coming-soon/privacy' },
    { key: 'security', href: '/coming-soon/security' },
    { key: 'institutional', href: '/coming-soon/institutions' },
  ] as const

  return (
    <footer className="border-t border-outline-variant/40 bg-surface-variant">
      <div className="mx-auto max-w-container-max px-gutter py-16">
        <div className="flex flex-col gap-10 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <p className="font-headline text-headline-md text-primary">{tApp('name')}</p>
            <p className="mt-3 text-body-sm text-on-surface-variant">{tApp('tagline')}</p>
          </div>

          <nav aria-label={tApp('name')}>
            <ul className="grid gap-3 sm:grid-cols-2 md:gap-x-16">
              {links.map(({ key, href }) => (
                <li key={key}>
                  <Link
                    href={href}
                    className="text-body-sm text-on-surface-variant transition-colors hover:text-primary"
                  >
                    {t(key)}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>

        <p className="mt-12 border-t border-outline-variant/40 pt-6 text-body-sm text-on-surface-variant">
          {t('copyright', { year: 2026 })}
        </p>
      </div>
    </footer>
  )
}
