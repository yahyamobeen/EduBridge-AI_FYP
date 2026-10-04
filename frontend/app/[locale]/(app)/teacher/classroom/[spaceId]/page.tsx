import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { TeacherClassroom } from '@/components/classroom/ClassroomView'

type Props = { params: Promise<{ locale: string; spaceId: string }> }

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'classroom' })
  return { title: t('title') }
}

// No generateStaticParams: the id is per user, and the data is fetched in the
// browser because the access token lives only in client memory.
export default async function Page({ params }: Props) {
  const { locale, spaceId } = await params
  setRequestLocale(locale)
  return <TeacherClassroom spaceId={spaceId} />
}
