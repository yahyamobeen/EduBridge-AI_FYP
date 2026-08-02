import { useTranslations } from 'next-intl'
import {
  ArrowIcon,
  CalendarIcon,
  ChartIcon,
  ChatIcon,
  GlobeIcon,
  SparkIcon,
  TeachIcon,
  UsersIcon,
} from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'

function RoleTag({
  icon,
  children,
  tone,
}: {
  icon: React.ReactNode
  children: React.ReactNode
  tone: string
}) {
  return (
    <p
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-label-caps uppercase ${tone}`}
    >
      {icon}
      {children}
    </p>
  )
}

/**
 * The prototype's 12-column bento: students take two thirds, teachers one
 * third, and parents span the full width beneath with the illustrative cards
 * ordered before the copy on desktop and after it on mobile.
 *
 * Role palettes are from DESIGN.md: student blue, teacher indigo, parent
 * neutral.
 */
export function Solutions() {
  const t = useTranslations('landing.solutions')

  return (
    <section
      id="solutions"
      className="relative scroll-mt-4 overflow-hidden bg-surface-container-lowest"
    >
      <div
        className="dot-pattern pointer-events-none absolute inset-0 opacity-50"
        aria-hidden
      />

      <div className="relative mx-auto max-w-container-max px-gutter py-32">
        <div className="reveal max-w-3xl">
          <h2 className="font-headline text-headline-lg text-on-primary-fixed md:text-display-md">
            {t('title')}
          </h2>
          <p className="mt-4 text-body-lg text-on-surface-variant">{t('subtitle')}</p>
        </div>

        <div className="mt-14 grid grid-cols-12 gap-6">
          {/* ---- Students: 8 of 12, split copy / preview ---- */}
          <article className="reveal bento-item col-span-12 flex flex-col md:flex-row lg:col-span-8">
            <div className="flex-1 p-7 md:p-9">
              <RoleTag
                icon={<SparkIcon className="h-4 w-4" />}
                tone="bg-student-blue text-primary"
              >
                {t('students.tag')}
              </RoleTag>
              <h3 className="mt-4 font-headline text-headline-md">{t('students.title')}</h3>
              <p className="mt-3 text-body-md text-on-surface-variant">{t('students.body')}</p>

              <ul className="mt-6 space-y-3">
                {(
                  [
                    ['featureLanguages', <GlobeIcon key="g" className="h-4 w-4" />],
                    ['featureMethod', <ChatIcon key="c" className="h-4 w-4" />],
                  ] as const
                ).map(([key, icon]) => (
                  <li key={key} className="flex items-start gap-3 text-body-sm">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-student-blue text-primary">
                      {icon}
                    </span>
                    <span className="pt-1">{t(`students.${key}`)}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Tutor preview panel */}
            <div className="flex items-center justify-center border-t border-outline-variant/40 bg-surface-container-low p-7 md:w-2/5 md:border-e-0 md:border-s md:border-t-0">
              <div className="parallax w-full space-y-3" data-parallax-speed="0.03">
                <p className="text-label-caps uppercase text-on-surface-variant">
                  {t('students.previewLabel')}
                </p>
                <div className="ms-auto w-11/12 rounded border border-outline-variant/40 bg-surface-container-lowest p-3 text-body-sm shadow-sm">
                  {t('students.previewAsk')}
                </div>
                <div className="w-11/12 rounded border border-tertiary/30 bg-tertiary-fixed/40 p-3 text-body-sm shadow-sm">
                  {t('students.previewAnswer')}
                </div>
                <div className="flex items-center gap-1.5 ps-1" aria-hidden>
                  <span className="h-1.5 w-1.5 rounded-full bg-tertiary/60" />
                  <span className="h-1.5 w-1.5 rounded-full bg-tertiary/40" />
                  <span className="h-1.5 w-1.5 rounded-full bg-tertiary/20" />
                </div>
              </div>
            </div>
          </article>

          {/* ---- Teachers: 4 of 12, with the mastery readout ---- */}
          <article className="reveal bento-item col-span-12 flex flex-col p-7 md:col-span-6 md:p-9 lg:col-span-4">
            <RoleTag
              icon={<TeachIcon className="h-4 w-4" />}
              tone="bg-surface-container-high text-teacher-indigo"
            >
              {t('teachers.tag')}
            </RoleTag>
            <h3 className="mt-4 font-headline text-headline-md">{t('teachers.title')}</h3>
            <p className="mt-3 flex-grow text-body-md text-on-surface-variant">
              {t('teachers.body')}
            </p>

            <div className="mt-6 rounded bg-surface-container-low p-4">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-body-sm font-semibold">{t('teachers.sampleTopic')}</span>
                <span className="text-body-sm font-semibold text-status-pending">
                  {t('teachers.sampleShare')}
                </span>
              </div>
              {/* Illustrative only: no analytics endpoint exists yet. */}
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-container-highest">
                <div className="h-full w-[72%] rounded-full bg-status-pending" />
              </div>
            </div>
          </article>

          {/* ---- Parents: full width, cards before copy on desktop ---- */}
          <article className="reveal bento-item col-span-12">
            <div className="grid grid-cols-1 md:grid-cols-2">
              <div className="order-2 grid gap-4 bg-surface-container-low p-7 md:order-1 md:p-9">
                <div className="parallax" data-parallax-speed="0.02">
                  <ChartIcon className="h-6 w-6 text-primary" />
                  <h4 className="mt-3 font-headline text-body-lg font-semibold">
                    {t('parents.cardMasteryTitle')}
                  </h4>
                  <p className="mt-1 text-body-sm text-on-surface-variant">
                    {t('parents.cardMasteryBody')}
                  </p>
                </div>
                <div className="parallax" data-parallax-speed="0.04">
                  <CalendarIcon className="h-6 w-6 text-secondary" />
                  <h4 className="mt-3 font-headline text-body-lg font-semibold">
                    {t('parents.cardPlannerTitle')}
                  </h4>
                  <p className="mt-1 text-body-sm text-on-surface-variant">
                    {t('parents.cardPlannerBody')}
                  </p>
                </div>
              </div>

              <div className="order-1 p-7 md:order-2 md:p-9">
                <RoleTag
                  icon={<UsersIcon className="h-4 w-4" />}
                  tone="bg-surface-container-high text-on-surface-variant"
                >
                  {t('parents.tag')}
                </RoleTag>
                <h3 className="mt-4 font-headline text-headline-md">{t('parents.title')}</h3>
                {/*
                  Wording matters here. The prototype's parent dashboard offered
                  a "replay this tutor session" control, which prd.md §4.2
                  forbids — a parent has no read path to a student's chat. The
                  copy promises progress visibility and says plainly that
                  sessions stay private, so the marketing does not advertise a
                  capability RLS denies.
                */}
                <p className="mt-3 text-body-md text-on-surface-variant">{t('parents.body')}</p>
                <Link
                  href="/signup"
                  className="mt-6 inline-flex items-center gap-2 text-body-sm font-semibold text-primary transition-colors hover:text-primary-container"
                >
                  {t('parents.cta')}
                  <ArrowIcon className="h-4 w-4 rtl:-scale-x-100" />
                </Link>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>
  )
}
