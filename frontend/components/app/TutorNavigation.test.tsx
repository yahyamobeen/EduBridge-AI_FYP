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
  getPhysicsTutorInfo: vi.fn(),
  listTutorSessions: vi.fn(),
  getTutorSession: vi.fn(),
}))

// `RequireRole` resolves `me` itself since classroom Phase 6c, so the dashboard no
// longer takes it as a prop. Stubbed to hand the render prop a fixed student: this
// file tests the tutor entry point, and RequireRole's own behaviour is covered by
// SessionGuard.test.tsx.
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

describe('AI Tutor Grade Guardrail and Navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Class 9 Student', () => {
    const class9Student: MeResponse = {
      ...baseStudent,
      profile: { ...baseStudent.profile!, class_level: 9 },
    }

    beforeEach(() => {
      currentStudent = class9Student
    })

    it('sidebar AI Tutor button opens the Subject Selection Modal', () => {
      render(
        <NextIntlClientProvider locale="en" messages={en}>
          <DashboardShell me={class9Student} subtitle="">
            <StudentDashboard />
          </DashboardShell>
        </NextIntlClientProvider>,
      )

      // In sidebar, find the AI Tutor button
      const tutorButtons = screen.getAllByRole('button', { name: en.nav.items.tutor })
      expect(tutorButtons.length).toBeGreaterThan(0)

      // Initially no modal dialog is open
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

      // Click sidebar tutor button
      fireEvent.click(tutorButtons[0]!)

      // SubjectModal dialog must now be open with 6 subjects
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByText(en.tutor.modal.title)).toBeInTheDocument()
      expect(screen.getByText(en.tutor.subjects.physics)).toBeInTheDocument()
      expect(screen.getByText(en.tutor.subjects.mathematics)).toBeInTheDocument()
    })

    it('dashboard AI Tutor card opens the Subject Selection Modal on click', () => {
      render(
        <NextIntlClientProvider locale="en" messages={en}>
          <DashboardShell me={class9Student} subtitle="">
            <StudentDashboard />
          </DashboardShell>
        </NextIntlClientProvider>,
      )

      // Find the card by its heading
      const tutorHeading = screen.getByRole('heading', { name: en.dashboard.cards.tutorTitle })
      const tutorCard = tutorHeading.closest('section')!
      expect(tutorCard).toBeInTheDocument()

      // Learn more button inside card
      const learnMoreBtn = within(tutorCard).getByRole('button', {
        name: en.dashboard.learnMore,
      })
      fireEvent.click(learnMoreBtn)

      // SubjectModal dialog must now be open
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(screen.getByText(en.tutor.modal.title)).toBeInTheDocument()
    })
  })

  describe('Non-Class 9 Student (Class 10)', () => {
    const class10Student: MeResponse = {
      ...baseStudent,
      profile: { ...baseStudent.profile!, class_level: 10 },
    }

    beforeEach(() => {
      currentStudent = class10Student
    })

    it('sidebar AI Tutor links to /coming-soon/tutor instead of opening modal', () => {
      render(
        <NextIntlClientProvider locale="en" messages={en}>
          <DashboardShell me={class10Student} subtitle="">
            <StudentDashboard />
          </DashboardShell>
        </NextIntlClientProvider>,
      )

      // In sidebar, find the AI Tutor link
      const tutorLinks = screen.getAllByRole('link', { name: en.nav.items.tutor })
      expect(tutorLinks.length).toBeGreaterThan(0)
      expect(tutorLinks[0]).toHaveAttribute('href', '/coming-soon/tutor')

      // Modal dialog should not be in the document
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('dashboard AI Tutor card links to /coming-soon/tutor instead of opening modal', () => {
      render(
        <NextIntlClientProvider locale="en" messages={en}>
          <DashboardShell me={class10Student} subtitle="">
            <StudentDashboard />
          </DashboardShell>
        </NextIntlClientProvider>,
      )

      const tutorHeading = screen.getByRole('heading', { name: en.dashboard.cards.tutorTitle })
      const tutorCard = tutorHeading.closest('section')!
      const tutorCardLink = within(tutorCard).getByRole('link', {
        name: en.dashboard.learnMore,
      })
      expect(tutorCardLink).toBeInTheDocument()
      expect(tutorCardLink).toHaveAttribute('href', '/coming-soon/tutor')

      // Click link
      fireEvent.click(tutorCardLink)

      // Modal should NOT be opened
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})
