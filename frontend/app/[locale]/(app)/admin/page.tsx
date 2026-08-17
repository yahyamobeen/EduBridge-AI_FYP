import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { AdminDashboard } from '@/components/app/Dashboards'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'dashboard.admin' })
  return { title: t('role') }
}

export default async function Page({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <AdminDashboard />
}
