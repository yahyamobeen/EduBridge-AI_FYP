import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { GuardianGate } from '@/components/auth/GuardianGate'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.guardian' })
  return { title: t('title') }
}

/**
 * Reached only for a Class 9–10 student whose `onboarding_state` is
 * `guardian_link_pending`. A Class 11–12 student has no code path here, because
 * the backend never puts them in that state (tdd.md §3.1) — the gate is not
 * something the client decides to show.
 */
export default async function GuardianGatePage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <GuardianGate />
}
