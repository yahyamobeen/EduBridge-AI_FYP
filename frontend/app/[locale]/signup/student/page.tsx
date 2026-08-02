import { getTranslations, setRequestLocale } from 'next-intl/server'
import { StudentSignupForm } from '@/components/signup/StudentSignupForm'
import { FormBanner } from '@/components/signup/fields'
import { getEnums } from '@/lib/api/endpoints'
import type { EnumsResponse } from '@/lib/api/types'

type Props = { params: Promise<{ locale: string }> }

/**
 * Reference data is fetched on the SERVER and passed down, so the academic step
 * has its options on first paint instead of showing a spinner on a slow
 * connection (prd.md A11Y-2).
 *
 * Safe to call here only because the endpoint takes no auth — the access token
 * lives in module state, which on the server is shared across requests
 * (see lib/api/endpoints.ts).
 */
export default async function StudentSignupPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)

  // Only the fetch is guarded: JSX constructed inside a try would not have its
  // render errors caught anyway, since React renders after this returns.
  let enums: EnumsResponse | null = null
  try {
    enums = await getEnums()
  } catch {
    enums = null
  }

  if (enums !== null) return <StudentSignupForm enums={enums} />

  const t = await getTranslations('signup.errors')
  return (
    <div className="mx-auto max-w-xl px-gutter py-24">
      <h1 className="font-headline text-headline-lg text-on-primary-fixed">
        {t('enumsTitle')}
      </h1>
      <p className="mt-3 text-body-md text-on-surface-variant">{t('enumsBody')}</p>
      <div className="mt-6">
        <FormBanner>{t('enumsRetry')}</FormBanner>
      </div>
    </div>
  )
}
