import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, expect, it, vi } from 'vitest'
import type { MeResponse } from '@/lib/api/types'
import en from '@/messages/en.json'
import { AppFrame } from './AppFrame'
import { TeacherDashboard } from './Dashboards'

/**
 * The teacher dashboard. Its "Class roster" placeholder was removed (owner
 * decision, 2026-10-06): it promised "who has not joined yet", which no
 * endpoint can know, and each classroom's People tab already is the roster. The
 * classroom card takes the row it shared.
 */

const LOADED = { timeout: 5_000 }

const teacher: MeResponse = {
  user_id: 't-1',
  email: 'teacher@example.com',
  full_name: 'Sir Ahmed',
  language_pref: 'en',
  role: 'teacher',
  onboarding_state: 'active',
  email_verified: true,
  two_factor: { enabled: true, method: 'totp' },
  profile: null,
  guardian: { required: false, status: null },
}

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/teacher',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({
  getMe: () => Promise.resolve(teacher),
  logout: () => Promise.resolve(),
  listSpaces: () => Promise.resolve({ spaces: [] }),
}))

function renderTeacher() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Karachi">
      <AppFrame>
        <TeacherDashboard />
      </AppFrame>
    </NextIntlClientProvider>,
  )
}

describe('the teacher dashboard', () => {
  it('has no "Class roster" placeholder', async () => {
    renderTeacher()
    await screen.findByRole('heading', { name: en.dashboard.cards.spacesTitle }, LOADED)
    expect(screen.queryByText('Class roster')).toBeNull()
    expect(screen.queryByText('Who is enrolled, and who has not joined yet.')).toBeNull()
  })

  it('gives the classroom card the whole row', async () => {
    renderTeacher()
    const heading = await screen.findByRole(
      'heading',
      { name: en.dashboard.cards.spacesTitle },
      LOADED,
    )
    expect(heading.closest('section')).toHaveClass('md:col-span-12')
  })
})
