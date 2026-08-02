import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { VerifyEmail } from '@/components/auth/VerifyEmail'

type Props = {
  params: Promise<{ locale: string }>
  searchParams: Promise<{ token?: string }>
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.verifyEmail' })
  return { title: t('verifyingTitle') }
}

/**
 * The token is read on the SERVER and passed down, rather than read from
 * `window.location` on the client: it arrives in the URL either way, and this
 * keeps the exchange out of a second render pass.
 */
export default async function VerifyEmailPage({ params, searchParams }: Props) {
  const { locale } = await params
  const { token } = await searchParams
  setRequestLocale(locale)
  return <VerifyEmail token={token ?? null} />
}
