import type { Metadata, Viewport } from 'next'
import type { ReactNode } from 'react'
import { notFound } from 'next/navigation'
import { hasLocale, NextIntlClientProvider } from 'next-intl'
import { getTranslations, setRequestLocale } from 'next-intl/server'
import { Footer } from '@/components/layout/Footer'
import { SkipLink } from '@/components/layout/SkipLink'
import { TopNav } from '@/components/layout/TopNav'
import { dirFor, routing } from '@/i18n/routing'
import { fontVariablesFor } from '../fonts'
import '../globals.css'

type Props = {
  children: ReactNode
  params: Promise<{ locale: string }>
}

/** Pre-renders all three locales at build time rather than on first request. */
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export async function generateMetadata({ params }: Omit<Props, 'children'>): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'app' })
  return { title: t('name'), description: t('tagline') }
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params

  // An unknown locale must 404 rather than silently fall back to English --
  // a student who lands on /pk/login should be told the page is wrong, not
  // handed a page in a language they may not read.
  if (!hasLocale(routing.locales, locale)) notFound()

  // Required for static rendering; without it every page opts into dynamic.
  setRequestLocale(locale)

  return (
    <html lang={locale} dir={dirFor(locale)} className={fontVariablesFor(locale)}>
      <body className="flex min-h-screen flex-col">
        <NextIntlClientProvider>
          <SkipLink />
          <TopNav />
          <main id="main" className="flex-1">
            {children}
          </main>
          <Footer />
        </NextIntlClientProvider>
      </body>
    </html>
  )
}
