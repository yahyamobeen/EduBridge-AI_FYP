import { fireEvent, render, screen, within } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import type { MeResponse } from '@/lib/api/types'
import { StudentDashboard } from './Dashboards'
import { DashboardShell } from './DashboardShell'

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => '/dashboard',
  Link: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api/endpoints', () => ({
  logout: vi.fn().mockResolvedValue(undefined),
  askTutor: vi.fn(),
  listTutorBooks: vi.fn(),
  listTutorSessions: vi.fn(),
  getTutorSession: vi.fn(),
  tutorPagePath: (bookId: string, page: number) => `/tutor/books/${bookId}/pages/${page}`,
}))

import { listTutorBooks } from '@/lib/api/endpoints'

// `RequireRole` resolves `me` itself since classroom Phase 6c, so the page no longer
// takes it as a prop. Stubbed to hand the render prop the student under test; its own
// behaviour is covered by SessionGuard.test.tsx, and what this file tests is the tutor
// entry point.
let currentStudent: MeResponse

vi.mock('./SessionGuard', () => ({
  RequireRole: ({ children }: { children: (me: MeResponse) => React.ReactNode }) =>
    children(currentStudent),
}))

vi.mock('@/components/app/ClassroomsCard', () => ({
  ClassroomsCard: () => null,
}))

const baseStudent: MeResponse = {
  user_id: 'u-std',
  email: 'student@example.com',
  full_name: 'Test Student',
  language_pref: 'en',
  role: 'student',
  onboarding_state: 'active',
  email_verified: true,
  two_factor: { enabled: false, method: null },
  profile: {
    board: 'PCTB',
    class_level: 9,
    student_group: 'science',
    medium: 'en',
    language_pref: 'en',
  },
  guardian: { required: false, status: null },
}

function renderDashboard(me: MeResponse) {
  currentStudent = me
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <DashboardShell me={me} subtitle="">
        <StudentDashboard />
      </DashboardShell>
    </NextIntlClientProvider>,
  )
}

// Since the many-books change (tdd.md §3.2a) every student has a tutor: the modal lists
// their own subjects and marks those without a book as coming soon. Class 9 is no longer
// special, so the same assertions hold for every class and both boards.
describe.each([
  ['Punjab Class 9', { board: 'PCTB' as const, class_level: 9 }],
  ['Sindh Class 10', { board: 'STBB' as const, class_level: 10 }],
  ['Punjab Class 11', { board: 'PCTB' as const, class_level: 11 }],
])('AI Tutor entry points — %s student', (_label, profile) => {
  const student: MeResponse = {
    ...baseStudent,
    profile: {
      ...baseStudent.profile!,
      ...profile,
      student_group: profile.class_level >= 11 ? 'pre_medical' : 'science',
    },
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listTutorBooks).mockResolvedValue({
      board: profile.board,
      class_level: profile.class_level,
      books: [{ book_id: 'X', subject: 'Chemistry', available: true }],
    })
  })

  it('the sidebar AI Tutor button opens the tutor', async () => {
    renderDashboard(student)

    const tutorButtons = screen.getAllByRole('button', { name: en.nav.items.tutor })
    expect(tutorButtons.length).toBeGreaterThan(0)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // No student is sent to the old coming-soon page any more.
    expect(screen.queryByRole('link', { name: en.nav.items.tutor })).not.toBeInTheDocument()

    fireEvent.click(tutorButtons[0]!)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText(en.tutor.subjects.chemistry)).toBeInTheDocument()
    expect(listTutorBooks).toHaveBeenCalledTimes(1)
  })

  it('the dashboard AI Tutor card opens the tutor and is not marked unavailable', async () => {
    renderDashboard(student)

    const tutorCard = screen
      .getByRole('heading', { name: en.dashboard.cards.tutorTitle })
      .closest('section')!
    expect(within(tutorCard).queryByText(en.dashboard.notYetAvailable)).toBeNull()

    fireEvent.click(within(tutorCard).getByRole('button', { name: en.dashboard.learnMore }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText(en.tutor.subjects.chemistry)).toBeInTheDocument()
  })
})
