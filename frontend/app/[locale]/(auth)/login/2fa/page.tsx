import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { TwoFactorChallenge } from '@/components/auth/TwoFactorChallenge'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.twoFactor' })
  return { title: t('title') }
}

/**
 * Reached only from /login, which puts the `pending_token` in memory first.
 * Opening it directly renders nothing and returns to sign-in — there is no
 * challenge to answer, and the token cannot be recovered from a URL or storage
 * by design (lib/auth/challenge.ts).
 */
export default async function TwoFactorPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <TwoFactorChallenge />
}
