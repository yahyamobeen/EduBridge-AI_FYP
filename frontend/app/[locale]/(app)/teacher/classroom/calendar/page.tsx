import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { TeacherCalendar } from '@/components/classroom/Calendar'

type Props = { params: Promise<{ locale: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'classroom.calendar' })
  return { title: t('title') }
}

// A static segment, so it takes precedence over the sibling [spaceId] route.
export default async function Page({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <TeacherCalendar />
}
