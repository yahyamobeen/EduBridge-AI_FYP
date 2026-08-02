import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { TwoFactorEnrollment } from '@/components/auth/TwoFactorEnrollment'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.enroll' })
  return { title: t('title') }
}

export default async function EnrollTwoFactorPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <TwoFactorEnrollment />
}
