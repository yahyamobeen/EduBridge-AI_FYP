import type { ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, expect, it, vi } from 'vitest'
import messages from '@/messages/en.json'
import { LanguageSwitcher } from './LanguageSwitcher'

const CURRENT_PATH = '/login'

// The locale-aware Link renders an <a> whose href already carries the locale
// prefix; the stub reproduces that so hrefs can be asserted.
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => CURRENT_PATH,
  Link: ({
    children,
    locale,
    href,
    ...rest
  }: ComponentProps<'a'> & { locale: string; href: string }) => (
    <a href={`/${locale}${href}`} {...rest}>
      {children}
    </a>
  ),
}))

function renderAt(locale: string) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <LanguageSwitcher />
    </NextIntlClientProvider>,
  )
}

describe('LanguageSwitcher', () => {
  it('offers all three languages, each named in its own script', () => {
    renderAt('en')
    expect(screen.getByRole('link', { name: 'English' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'اردو' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Roman Urdu' })).toBeInTheDocument()
  })

  it('marks only the active language with aria-current', () => {
    renderAt('ur')
    expect(screen.getByRole('link', { name: 'اردو' })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('link', { name: 'English' })).not.toHaveAttribute('aria-current')
  })

  it('keeps the user on the same page when switching language', () => {
    // Switching language mid-journey must not bounce the user to the home page.
    renderAt('en')
    expect(screen.getByRole('link', { name: 'اردو' })).toHaveAttribute(
      'href',
      `/ur${CURRENT_PATH}`,
    )
    expect(screen.getByRole('link', { name: 'Roman Urdu' })).toHaveAttribute(
      'href',
      `/ur-Latn${CURRENT_PATH}`,
    )
  })

  it('tags the Urdu option with lang so it renders in the Naskh face', () => {
    // Without this the endonym falls back to a Latin face and mangles the script.
    renderAt('en')
    expect(screen.getByRole('link', { name: 'اردو' })).toHaveAttribute('lang', 'ur')
    expect(screen.getByRole('link', { name: 'English' })).not.toHaveAttribute('lang')
  })

  it('labels the switcher for screen readers', () => {
    renderAt('en')
    expect(screen.getByRole('navigation', { name: 'Language' })).toBeInTheDocument()
  })
})
