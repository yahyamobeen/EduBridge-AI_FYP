import { useTranslations } from 'next-intl'
import { BookIcon, GlobeIcon, ShieldIcon, SparkIcon } from '@/components/ui/Icon'

const ITEMS = [
  { key: 'curriculum', Icon: BookIcon, tone: 'bg-student-blue text-primary' },
  { key: 'bilingual', Icon: GlobeIcon, tone: 'bg-tertiary-fixed text-tertiary' },
  {
    key: 'grounded',
    Icon: ShieldIcon,
    tone: 'bg-secondary-container text-on-secondary-container',
  },
  { key: 'adaptive', Icon: SparkIcon, tone: 'bg-surface-container-high text-teacher-indigo' },
] as const

export function Capabilities() {
  const t = useTranslations('landing.capabilities')

  return (
    <section className="border-t border-outline-variant/40 bg-surface">
      <div className="mx-auto max-w-container-max px-gutter py-32">
        <div className="reveal max-w-3xl">
          <h2 className="font-headline text-headline-lg text-on-primary-fixed md:text-display-md">
            {t('title')}
          </h2>
          <p className="mt-4 text-body-lg text-on-surface-variant">{t('subtitle')}</p>
        </div>

        <ul className="stagger mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {ITEMS.map(({ key, Icon, tone }) => (
            <li
              key={key}
              className="capability-card rounded border border-outline-variant/60 bg-surface-container-lowest p-6"
            >
              <span
                className={`flex h-11 w-11 items-center justify-center rounded ${tone}`}
                aria-hidden
              >
                <Icon className="h-5 w-5" />
              </span>
              <h3 className="mt-5 font-headline text-body-lg font-semibold">
                {t(`${key}Title`)}
              </h3>
              <p className="mt-2 text-body-sm text-on-surface-variant">{t(`${key}Body`)}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
