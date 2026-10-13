import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, expect, it, vi } from 'vitest'
import type { MeResponse, SpaceSummary } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { AppFrame } from '@/components/app/AppFrame'
import { StudentClassrooms, TeacherClassrooms } from './Classrooms'

/**
 * The two classroom lists, and the three-locale render check: next-intl
 * reports a missing key through `onError` rather than throwing, so an
 * untranslated string would otherwise pass silently (the Landing.test.tsx rule).
 */

/**
 * The first wait in each test covers SessionGuard's identity check AND the list
 * fetch. Testing Library's default is 1s; inside the full suite, where workers
 * compete for CPU, that measured the machine rather than the code — the same
 * class of false failure `vitest.config.mts` records raising `testTimeout` for.
 */
const LOADED = { timeout: 5_000 }

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/classroom',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

let me: MeResponse
let spaces: SpaceSummary[]
vi.mock('@/lib/api/endpoints', () => ({
  getMe: () => Promise.resolve(me),
  logout: () => Promise.resolve(),
  listSpaces: () => Promise.resolve({ spaces }),
  joinSpace: vi.fn(),
  getEnums: () => Promise.resolve({ boards: [], class_levels: [], groups_by_class: {} }),
  listSubjects: vi.fn(),
  createSpace: vi.fn(),
}))

function identity(role: 'student' | 'teacher'): MeResponse {
  return {
    user_id: 'u-1',
    email: 'u@example.com',
    full_name: 'Aisha Khan',
    language_pref: 'en',
    role,
    onboarding_state: 'active',
    email_verified: true,
    two_factor: { enabled: true, method: 'totp' },
    profile: null,
    guardian: { required: false, status: null },
  }
}

const SPACE: SpaceSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  title: 'Physics 11-A',
  status: 'active',
  subject: { id: 'sub', name: 'Physics', board: 'PCTB', class_level: 11 },
  owner_name: 'Sir Ahmed',
  viewer_role: 'member',
  can_manage: false,
  member_count: null,
  joined_at: '2026-10-01T10:00:00Z',
}

type Messages = typeof en

function renderIn(
  node: React.ReactNode,
  locale = 'en',
  messages: Messages = en,
  onError = vi.fn(),
) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages} onError={onError}>
      {/* The (app) layout's frame: the identity check and the sidebar (Phase 6c). */}
      <AppFrame>{node}</AppFrame>
    </NextIntlClientProvider>,
  )
}

describe('the student list', () => {
  it('links each class to its own page and shows the teacher, never a head count', async () => {
    me = identity('student')
    spaces = [SPACE]
    renderIn(<StudentClassrooms />)
    const link = await screen.findByRole('link', { name: /Physics 11-A/ }, LOADED)
    expect(link).toHaveAttribute('href', `/classroom/${SPACE.id}`)
    expect(link).toHaveTextContent('Teacher: Sir Ahmed')
    expect(screen.getByRole('heading', { name: en.classroom.join.heading })).toBeInTheDocument()
  })

  it('says what to do when there are no classes', async () => {
    me = identity('student')
    spaces = []
    renderIn(<StudentClassrooms />)
    expect(await screen.findByText(en.classroom.student.empty, {}, LOADED)).toBeInTheDocument()
  })
})

describe('the teacher list', () => {
  it('shows the head count and the create form', async () => {
    me = identity('teacher')
    spaces = [
      { ...SPACE, viewer_role: 'owner', can_manage: true, member_count: 3, joined_at: null },
    ]
    renderIn(<TeacherClassrooms />)
    const link = await screen.findByRole('link', { name: /Physics 11-A/ }, LOADED)
    expect(link).toHaveAttribute('href', `/teacher/classroom/${SPACE.id}`)
    expect(link).toHaveTextContent('3 students')
    expect(
      screen.getByRole('heading', { name: en.classroom.create.heading }),
    ).toBeInTheDocument()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders both lists fully in %s with no missing keys', async (locale, messages) => {
    const onError = vi.fn()
    spaces = [SPACE]
    me = identity('student')
    const student = renderIn(<StudentClassrooms />, locale, messages as Messages, onError)
    expect(
      await screen.findByRole('link', { name: /Physics 11-A/ }, LOADED),
    ).toBeInTheDocument()
    student.unmount()
    me = identity('teacher')
    spaces = [
      { ...SPACE, viewer_role: 'owner', can_manage: true, member_count: 1, joined_at: null },
    ]
    renderIn(<TeacherClassrooms />, locale, messages as Messages, onError)
    expect(
      await screen.findByRole('link', { name: /Physics 11-A/ }, LOADED),
    ).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalled()
  })
})
