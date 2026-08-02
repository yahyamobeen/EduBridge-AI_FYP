import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { PlanSelection } from '@/components/auth/PlanSelection'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'plan' })
  return { title: t('title') }
}

/**
 * Reached after the guardian gate, and AGAIN whenever a trial lapses — this is
 * the one onboarding step a user can arrive at after having been `active`
 * (prd.md §2.6 MON-4).
 */
export default async function PlanPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <PlanSelection />
}
