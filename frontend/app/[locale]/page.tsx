import { useTranslations } from 'next-intl'
import { setRequestLocale } from 'next-intl/server'
import { dirFor } from '@/i18n/routing'

type Props = { params: Promise<{ locale: string }> }

/**
 * Placeholder root. The real landing page is Phase 4; this exists so the app
 * runs, and so the token and locale wiring is visible.
 */
export default async function Page({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <Scaffold dir={dirFor(locale)} />
}

function Scaffold({ dir }: { dir: string }) {
  const t = useTranslations('scaffold')
  const tApp = useTranslations('app')

  return (
    <div className="mx-auto max-w-container-max px-margin-mobile py-16 md:px-margin-desktop">
      <p className="text-label-caps uppercase text-on-surface-variant">{t('eyebrow')}</p>
      <h1 className="mt-2 font-headline text-headline-lg-mobile md:text-headline-lg">
        {tApp('name')}
      </h1>
      <p className="mt-4 max-w-prose text-body-md text-on-surface-variant">{t('body')}</p>
      <p className="mt-2 text-body-sm text-on-surface-variant">{t('directionNote', { dir })}</p>

      {/* Renders the role palettes from DESIGN.md so a token regression is
          visible rather than silent. */}
      <ul className="mt-8 flex flex-wrap gap-3" aria-label={t('paletteLabel')}>
        <li className="rounded bg-student-blue px-3 py-2 text-body-sm text-on-surface">
          {t('student')}
        </li>
        <li className="rounded bg-teacher-indigo px-3 py-2 text-body-sm text-white">
          {t('teacher')}
        </li>
        <li className="rounded bg-surface-container-high px-3 py-2 text-body-sm text-on-surface">
          {t('parent')}
        </li>
      </ul>
    </div>
  )
}
