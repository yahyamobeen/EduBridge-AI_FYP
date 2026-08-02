import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { CheckEmail } from '@/components/auth/CheckEmail'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.checkEmail' })
  return { title: t('title') }
}

export default async function CheckEmailPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <CheckEmail />
}
