import { getTranslations, setRequestLocale } from 'next-intl/server'
import type { Metadata } from 'next'
import { AdminLoginForm } from '@/components/auth/AdminLoginForm'

type Props = { params: Promise<{ locale: string }> }

/**
 * Administrator sign-in, reached ONLY through the rewrite in `proxy.ts`.
 *
 * `/[locale]/admin-login` itself is answered with a 404 by that middleware, so
 * this file has no directly reachable URL. It lives in the `(auth)` group — not
 * `(site)` — because that group renders no top nav and no footer: an unlisted
 * operations door must not carry the marketing chrome, and a half-authenticated
 * visitor has nowhere legitimate to navigate to.
 *
 * ⚠️ Neither the secret path nor the 404 is the security control. The control is
 *    `POST /api/auth/admin/login`, which refuses non-administrators with a 401
 *    identical to a wrong password.
 */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'auth.adminLogin' })
  return {
    title: t('title'),
    // Belt and braces. The page is unreachable without the secret path and is
    // in no sitemap, but a crawler that somehow follows one must not index it.
    robots: { index: false, follow: false },
  }
}

export default async function AdminLoginPage({ params }: Props) {
  const { locale } = await params
  setRequestLocale(locale)
  return <AdminLoginForm />
}
