import { notFound } from 'next/navigation'
import { getTranslations, setRequestLocale } from 'next-intl/server'
import { ArrowIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { routing } from '@/i18n/routing'

/**
 * Destination for prototype links whose product areas are not built yet:
 * the Curriculum / Tutor / Progress nav items, "Institution Demo", and the
 * footer's policy and institutional links.
 *
 * Better than `href="#"` (which reads as broken) and better than deleting the
 * links (which loses the prototype's navigation).
 */
const SLUGS = [
  'curriculum',
  'tutor',
  'progress',
  'institutions',
  'integrity',
  'privacy',
  'security',
  // The auth screens carry their own minimal footer (Help / Privacy / Terms).
  'help',
  'terms',
  // Every non-dashboard destination in NAV_BY_ROLE. Each is a real product area
  // from prd.md §4.2 that later phases build; until then the nav points here
  // rather than nowhere.
  'practice',
  'quizzes',
  'my-classes',
  'planner',
  'settings',
  'spaces',
  'reports',
  'roster',
  'slo',
  'announcements',
  'my-child',
  'how-to-help',
] as const

type Slug = (typeof SLUGS)[number]

/** Slugs with their own label; the rest reuse the generic heading. */
const NAMED: Partial<Record<Slug, string>> = {
  curriculum: 'curriculum',
  tutor: 'tutor',
  progress: 'progress',
  institutions: 'institutions',
}

export function generateStaticParams() {
  return routing.locales.flatMap((locale) => SLUGS.map((slug) => ({ locale, slug })))
}

type Props = { params: Promise<{ locale: string; slug: string }> }

export default async function ComingSoonPage({ params }: Props) {
  const { locale, slug } = await params
  if (!(SLUGS as readonly string[]).includes(slug)) notFound()
  setRequestLocale(locale)

  const t = await getTranslations('comingSoon')
  const labelKey = NAMED[slug as Slug]
  const feature = labelKey ? t(labelKey) : t('eyebrow')

  return (
    <div className="mx-auto max-w-container-max px-gutter py-24 md:py-32">
      <p className="text-label-caps uppercase text-on-surface-variant">{t('eyebrow')}</p>
      <h1 className="mt-3 max-w-3xl font-headline text-headline-lg text-on-primary-fixed md:text-display-md">
        {t('title', { feature })}
      </h1>
      <p className="mt-6 max-w-xl text-body-lg text-on-surface-variant">{t('body')}</p>

      <div className="mt-10 flex flex-wrap items-center gap-4">
        <Link
          href="/signup"
          className="inline-flex items-center gap-2 rounded bg-primary-container px-6 py-3.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary"
        >
          {t('cta')}
          <ArrowIcon className="h-5 w-5 rtl:-scale-x-100" />
        </Link>
        <Link
          href="/"
          className="rounded border border-outline px-6 py-3.5 text-body-md font-semibold text-on-surface transition-colors hover:bg-surface-container-high"
        >
          {t('back')}
        </Link>
      </div>
    </div>
  )
}
