import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { GuardianConfirmGate } from '@/components/auth/GuardianConfirmGate'

type Props = {
  params: Promise<{ locale: string }>
  searchParams: Promise<{ token?: string }>
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.guardianConfirm' })
  return { title: t('title') }
}

/**
 * Where the invitation email lands. The parent must already hold an account —
 * `guardian/confirm` is authenticated as the parent (v0.3.2, decision 5) — so
 * this screen offers sign-up when there is no session rather than pretending it
 * can confirm on their behalf.
 */
export default async function GuardianConfirmPage({ params, searchParams }: Props) {
  const { locale } = await params
  const { token } = await searchParams
  setRequestLocale(locale)
  return <GuardianConfirmGate token={token ?? null} />
}
