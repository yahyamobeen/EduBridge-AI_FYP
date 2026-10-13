import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { TeacherClassrooms } from '@/components/classroom/Classrooms'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'classroom.teacher' })
  return { title: t('title') }
}

export default async function Page({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <TeacherClassrooms />
}
