import { useTranslations } from 'next-intl'
import { ShaderBackdrop } from '@/components/motion/ShaderBackdrop'
import { ArrowIcon, BookIcon, ChevronDownIcon, ShieldIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'

/**
 * Measured against the prototype in a browser rather than eyeballed:
 * h1 48px / 56px / -0.02em in #00174d, with the accent span a SOLID #003fb1
 * (the prototype uses no gradient), hero min-height 90vh, container padding
 * 24px.
 */
export function Hero() {
  const t = useTranslations('landing.hero')

  return (
    <header className="relative flex min-h-[90vh] items-center overflow-hidden">
      <ShaderBackdrop />

      <div className="relative mx-auto w-full max-w-container-max px-gutter py-20">
        <div className="stagger flex max-w-4xl flex-col items-start">
          <ul className="flex flex-wrap gap-3">
            <li className="inline-flex items-center gap-2 rounded-full border border-outline-variant/40 bg-surface-container-lowest/80 px-4 py-1.5 text-label-caps uppercase text-on-surface-variant backdrop-blur">
              <BookIcon className="h-4 w-4 text-primary" />
              {t('badgeCurriculum')}
            </li>
            <li className="inline-flex items-center gap-2 rounded-full border border-secondary/20 bg-secondary-container/60 px-4 py-1.5 text-label-caps uppercase text-on-secondary-container backdrop-blur">
              <ShieldIcon className="h-4 w-4" />
              {t('badgeSecurity')}
            </li>
          </ul>

          <h1 className="mt-8 font-headline text-headline-lg text-on-primary-fixed md:text-display-md">
            {t('titleLead')} <span className="text-primary">{t('titleAccent')}</span>
          </h1>

          <p className="mt-6 max-w-2xl text-body-lg text-on-surface-variant">{t('subtitle')}</p>

          <div className="mt-10 flex w-full flex-col gap-4 sm:w-auto sm:flex-row sm:items-center">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center gap-2 rounded bg-primary-container px-8 py-4 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary motion-safe:animate-pulse-ring"
            >
              {t('ctaPrimary')}
              {/* Points in the reading direction, so it mirrors in Urdu. */}
              <ArrowIcon className="h-5 w-5 rtl:-scale-x-100" />
            </Link>

            {/*
              "Institution Demo" is kept from the prototype. There is no
              institutional route in v1 (prd.md §15 CL-6 attaches institutions
              through classroom join codes), so it goes to the coming-soon page
              rather than a dead link.
            */}
            <Link
              href="/coming-soon/institutions"
              className="inline-flex items-center justify-center rounded border border-outline bg-surface-container-lowest/70 px-8 py-4 text-body-md font-semibold text-on-surface backdrop-blur transition-colors hover:bg-surface-container-high"
            >
              {t('ctaSecondary')}
            </Link>
          </div>
        </div>
      </div>

      <a
        href="#solutions"
        className="absolute inset-x-0 bottom-8 mx-auto flex w-fit flex-col items-center gap-1 text-on-surface-variant transition-colors hover:text-primary"
      >
        <span className="sr-only">{t('seeSolutions')}</span>
        <ChevronDownIcon className="h-6 w-6 motion-safe:animate-bob-down" />
      </a>
    </header>
  )
}
