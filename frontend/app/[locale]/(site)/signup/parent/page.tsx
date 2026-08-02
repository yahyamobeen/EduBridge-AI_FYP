import { setRequestLocale } from 'next-intl/server'
import { SimpleSignupForm } from '@/components/signup/SimpleSignupForm'

type Props = { params: Promise<{ locale: string }> }

/**
 * Parents self-register: the guardian confirmation flow requires an existing,
 * separately authenticated parent account before a Class 9-10 student's gate
 * can clear (prd.md §4.3).
 */
export default async function ParentSignupPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <SimpleSignupForm role="parent" />
}
