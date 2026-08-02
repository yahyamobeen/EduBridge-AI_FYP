import { setRequestLocale } from 'next-intl/server'
import { SimpleSignupForm } from '@/components/signup/SimpleSignupForm'

type Props = { params: Promise<{ locale: string }> }

export default async function TeacherSignupPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <SimpleSignupForm role="teacher" />
}
