import { useTranslations } from 'next-intl'
import { setRequestLocale } from 'next-intl/server'
import { ArrowIcon, SparkIcon, TeachIcon, UsersIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'

type Props = { params: Promise<{ locale: string }> }

/**
 * Role selection, from the choose-your-path prototype: three cards in a
 * 1/3-column grid, each dropping in from above with a staggered delay, and
 * each taking its own accent colour on hover (primary / teacher-indigo /
 * tertiary).
 */
const ROLES = [
  {
    key: 'student',
    href: '/signup/student',
    Icon: SparkIcon,
    hover: 'hover:border-primary',
    chip: 'bg-student-blue text-primary',
    delay: 'motion-safe:[animation-delay:100ms]',
  },
  {
    key: 'teacher',
    href: '/signup/teacher',
    Icon: TeachIcon,
    hover: 'hover:border-teacher-indigo',
    chip: 'bg-surface-container-high text-teacher-indigo',
    delay: 'motion-safe:[animation-delay:300ms]',
  },
  {
    key: 'parent',
    href: '/signup/parent',
    Icon: UsersIcon,
    hover: 'hover:border-tertiary',
    chip: 'bg-tertiary-fixed text-tertiary',
    delay: 'motion-safe:[animation-delay:500ms]',
  },
] as const

export default async function SignupRolePage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <RoleChooser />
}

function RoleChooser() {
  const t = useTranslations('signup.role')

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-container-max flex-col justify-center px-gutter py-20">
      <div className="mb-12 text-center motion-safe:animate-roll-down">
        <h1 className="font-headline text-headline-lg text-on-primary-fixed md:text-display-md">
          {t('title')}
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-body-lg text-on-surface-variant">
          {t('subtitle')}
        </p>
      </div>

      <ul className="grid w-full grid-cols-1 gap-gutter md:grid-cols-3">
        {ROLES.map(({ key, href, Icon, hover, chip, delay }) => (
          <li key={key} className={`opacity-0 motion-safe:animate-roll-down ${delay}`}>
            {/* The whole card is the link, so the target is the full area
                rather than a small text hit-box on a phone. */}
            <Link
              href={href}
              className={`group flex h-full flex-col rounded-xl border border-outline-variant bg-surface-container-lowest p-8 shadow-sm transition-all duration-300 hover:shadow-md ${hover}`}
            >
              <span
                className={`flex h-12 w-12 items-center justify-center rounded-full ${chip}`}
                aria-hidden
              >
                <Icon className="h-6 w-6" />
              </span>

              <h2 className="mt-6 font-headline text-headline-md">{t(`${key}Tag`)}</h2>
              <p className="mt-1 text-label-caps uppercase text-on-surface-variant">
                {t(`${key}Lead`)}
              </p>
              <p className="mt-4 flex-grow text-body-md text-on-surface-variant">
                {t(`${key}Body`)}
              </p>

              <span className="mt-8 inline-flex items-center gap-2 text-body-sm font-semibold text-primary">
                {t(`${key}Cta`)}
                <ArrowIcon className="h-4 w-4 transition-transform group-hover:translate-x-1 rtl:-scale-x-100 rtl:group-hover:-translate-x-1" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
