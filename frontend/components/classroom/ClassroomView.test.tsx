import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MeResponse, PeopleResponse, SpaceDetail } from '@/lib/api/types'
import en from '@/messages/en.json'
import { StudentClassroom, TeacherClassroom } from './ClassroomView'

/**
 * One classroom, both roles.
 *
 * The rule under test: OWNER CONTROLS FOLLOW THE SERVER'S `viewer_role` AND
 * `can_manage`, never the role in the session. A member must see no code, no
 * remove button and no archive; a de-scoped owner must see none either, and be
 * told why (prd.md §4.2: never render a control the caller cannot use).
 */

/** First waits cover SessionGuard plus a fetch; see the note in Classrooms.test.tsx. */
const LOADED = { timeout: 5_000 }

const push = vi.fn()
vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => '/classroom/x',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const SPACE_ID = '11111111-1111-4111-8111-111111111111'
const getSpace = vi.fn()
const getPeople = vi.fn()
const leaveSpace = vi.fn()
const removeMember = vi.fn()
const changeJoinCode = vi.fn()
let me: MeResponse
vi.mock('@/lib/api/endpoints', () => ({
  getMe: () => Promise.resolve(me),
  logout: () => Promise.resolve(),
  getSpace: (...a: unknown[]) => getSpace(...a),
  getPeople: (...a: unknown[]) => getPeople(...a),
  leaveSpace: (...a: unknown[]) => leaveSpace(...a),
  removeMember: (...a: unknown[]) => removeMember(...a),
  changeJoinCode: (...a: unknown[]) => changeJoinCode(...a),
  updateSpace: vi.fn(),
  // The Stream is the default tab (Phase 3); these tests are about People.
  listAnnouncements: () => Promise.resolve({ items: [], next_cursor: null }),
  // Classwork, opened directly by a calendar link (Phase 5).
  getAssignment: (...a: unknown[]) => getAssignment(...a),
  listAssignments: () => Promise.resolve({ items: [], next_cursor: null }),
}))

const getAssignment = vi.fn()
const ASSIGNMENT_ID = '22222222-2222-4222-8222-222222222222'

function identity(role: 'student' | 'teacher'): MeResponse {
  return {
    user_id: role === 'teacher' ? 't-1' : 's-1',
    email: `${role}@example.com`,
    full_name: role === 'teacher' ? 'Sir Ahmed' : 'Aisha Khan',
    language_pref: 'en',
    role,
    onboarding_state: 'active',
    email_verified: true,
    two_factor: { enabled: true, method: 'totp' },
    profile: null,
    guardian: { required: false, status: null },
  }
}

function space(overrides: Partial<SpaceDetail> = {}): SpaceDetail {
  return {
    id: SPACE_ID,
    title: 'Physics 11-A',
    status: 'active',
    subject: { id: 'sub', name: 'Physics', board: 'PCTB', class_level: 11 },
    owner_name: 'Sir Ahmed',
    viewer_role: 'member',
    can_manage: false,
    member_count: null,
    joined_at: '2026-10-01T10:00:00Z',
    join_code: null,
    ...overrides,
  }
}

const PEOPLE: PeopleResponse = {
  owner: { user_id: 't-1', full_name: 'Sir Ahmed' },
  members: [
    { user_id: 's-1', full_name: 'Aisha Khan', joined_at: '2026-10-01T10:00:00Z', muted: null },
  ],
}

function wrap(node: React.ReactNode) {
  // `timeZone` as PlanSelection.test.tsx passes it: the app configures no global
  // zone, so a formatted date would otherwise log ENVIRONMENT_FALLBACK.
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Karachi">
      {node}
    </NextIntlClientProvider>,
  )
}

/**
 * The People card — behind its tab since Phase 3 (the Stream is the default).
 * Scoped, because the signed-in student's own name is also in the sidebar.
 */
async function peopleSection() {
  const tab = await screen.findByRole('tab', { name: en.classroom.tabs.people }, LOADED)
  if (tab.getAttribute('aria-selected') !== 'true') await userEvent.click(tab)
  const heading = await screen.findByRole(
    'heading',
    { name: en.classroom.people.heading },
    LOADED,
  )
  return heading.closest('section') as HTMLElement
}

beforeEach(() => {
  vi.clearAllMocks()
  getPeople.mockResolvedValue(PEOPLE)
})

describe('a member', () => {
  beforeEach(() => {
    me = identity('student')
    getSpace.mockResolvedValue(space())
  })

  it('sees the class and its people, and no owner control of any kind', async () => {
    wrap(<StudentClassroom spaceId={SPACE_ID} />)
    expect(
      await screen.findByRole('heading', { name: 'Physics 11-A' }, LOADED),
    ).toBeInTheDocument()
    expect(
      await within(await peopleSection()).findByText('Aisha Khan', {}, LOADED),
    ).toBeInTheDocument()
    expect(screen.queryByText(en.classroom.code.heading)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: en.classroom.people.remove })).toBeNull()
    expect(screen.queryByRole('button', { name: en.classroom.manage.archive })).toBeNull()
  })

  it('leaves only after confirming, then returns to the list', async () => {
    leaveSpace.mockResolvedValue(undefined)
    wrap(<StudentClassroom spaceId={SPACE_ID} />)
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.leave.button }, LOADED),
    )
    expect(leaveSpace).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    await userEvent.click(
      Array.from(dialog.querySelectorAll('button')).find(
        (b) => b.textContent === en.classroom.leave.button,
      )!,
    )
    expect(leaveSpace).toHaveBeenCalledWith(SPACE_ID)
    await waitFor(() => expect(push).toHaveBeenCalledWith('/classroom'))
  })
})

describe('the owner', () => {
  beforeEach(() => {
    me = identity('teacher')
    getSpace.mockResolvedValue(
      space({ viewer_role: 'owner', can_manage: true, member_count: 1, join_code: 'ABCD2345' }),
    )
  })

  it('sees the code, management and per-student removal', async () => {
    wrap(<TeacherClassroom spaceId={SPACE_ID} />)
    expect(await screen.findByText('ABCD2345', {}, LOADED)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: en.classroom.manage.archive }),
    ).toBeInTheDocument()
    const people = await peopleSection()
    expect(
      await within(people).findByRole('button', { name: en.classroom.people.remove }, LOADED),
    ).toBeInTheDocument()
  })

  it('removes a student only after confirming', async () => {
    removeMember.mockResolvedValue(undefined)
    wrap(<TeacherClassroom spaceId={SPACE_ID} />)
    await userEvent.click(
      await within(await peopleSection()).findByRole(
        'button',
        { name: en.classroom.people.remove },
        LOADED,
      ),
    )
    expect(removeMember).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveAccessibleName(/Remove Aisha Khan\?/)
    await userEvent.click(
      Array.from(dialog.querySelectorAll('button')).find(
        (b) => b.textContent === en.classroom.people.remove,
      )!,
    )
    expect(removeMember).toHaveBeenCalledWith(SPACE_ID, 's-1')
    const people = await peopleSection()
    await waitFor(() => expect(within(people).queryByText('Aisha Khan')).toBeNull())
  })
})

describe('an owner whose subject scope was revoked', () => {
  it('is told why and offered no controls', async () => {
    me = identity('teacher')
    getSpace.mockResolvedValue(
      space({ viewer_role: 'owner', can_manage: false, member_count: 1 }),
    )
    wrap(<TeacherClassroom spaceId={SPACE_ID} />)
    expect(
      await screen.findByText(en.classroom.detail.revokedNotice, {}, LOADED),
    ).toBeInTheDocument()
    expect(screen.queryByText(en.classroom.code.heading)).toBeNull()
    expect(screen.queryByRole('button', { name: en.classroom.manage.archive })).toBeNull()
    // People is owner-or-member only on the server too; it is not even requested.
    expect(getPeople).not.toHaveBeenCalled()
  })
})

describe('the id in the URL', () => {
  it('is refused without a request when it is not a UUID', async () => {
    me = identity('student')
    wrap(<StudentClassroom spaceId="../../admin" />)
    expect(
      await screen.findByText(en.classroom.detail.unavailable, {}, LOADED),
    ).toBeInTheDocument()
    expect(getSpace).not.toHaveBeenCalled()
  })
})

describe('a link to an assignment (from the calendar)', () => {
  beforeEach(() => {
    me = identity('student')
    getSpace.mockResolvedValue(space())
    getAssignment.mockReturnValue(new Promise(() => {}))
  })

  it('opens Classwork on that assignment', async () => {
    wrap(<StudentClassroom spaceId={SPACE_ID} assignmentId={ASSIGNMENT_ID} />)
    const tab = await screen.findByRole('tab', { name: en.classroom.tabs.classwork }, LOADED)
    expect(tab).toHaveAttribute('aria-selected', 'true')
    // The fetch runs in AssignmentView's effect, which can land a moment after the tab
    // appears under full-suite load: wait for it rather than assert at once.
    await waitFor(() =>
      expect(getAssignment).toHaveBeenCalledWith(ASSIGNMENT_ID, expect.any(AbortSignal)),
    )
  })

  it('ignores an id that is not a UUID and opens the Stream', async () => {
    wrap(<StudentClassroom spaceId={SPACE_ID} assignmentId="../x" />)
    const tab = await screen.findByRole('tab', { name: en.classroom.tabs.stream }, LOADED)
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(getAssignment).not.toHaveBeenCalled()
  })
})
