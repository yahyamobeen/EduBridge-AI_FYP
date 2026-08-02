import { useTranslations } from 'next-intl'

export function Footer() {
  const t = useTranslations('footer')
  const tApp = useTranslations('app')

  return (
    <footer className="mt-16 border-t border-outline-variant bg-surface-container-lowest">
      <div className="mx-auto flex max-w-container-max flex-col gap-3 px-margin-mobile py-8 md:flex-row md:items-center md:justify-between md:px-margin-desktop">
        <p className="text-body-sm text-on-surface-variant">
          {tApp('name')} &mdash; {t('rights')}
        </p>
        <ul className="flex flex-wrap gap-4 text-body-sm text-on-surface-variant">
          {/* Real routes arrive with the legal pages; listed here so the shell
              is complete, and deliberately not `href="#"`. */}
          <li>{t('privacy')}</li>
          <li>{t('terms')}</li>
          <li>{t('support')}</li>
        </ul>
      </div>
    </footer>
  )
}
