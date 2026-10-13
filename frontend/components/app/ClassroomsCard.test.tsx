import { render, screen, within } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SpaceSummary } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { ClassroomsCard } from './ClassroomsCard'

/**
 * The dashboard's classroom card (classroom Phase 6c, owner report
 * 2026-10-05: it "still says coming soon"). What must hold: it lists the
 * caller's real classrooms and links into each; it never shows "Not available
 * yet", because the feature is available — not even when the request fails;
 * and an empty list says what to do next.
 */

const listSpaces = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  listSpaces: (...a: unknown[]) => listSpaces(...a),
}))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const LOADED = { timeout: 5_000 }

function space(n: number, overrides: Partial<SpaceSummary> = {}): SpaceSummary {
  return {
    id: `00000000-0000-4000-8000-00000000000${n}`,
    title: `Physics 11-${n}`,
    status: 'active',
    subject: { id: 'sub', name: 'Physics', board: 'PCTB', class_level: 11 },
    owner_name: 'Sir Ahmed',
    viewer_role: 'member',
    can_manage: false,
    member_count: null,
    joined_at: '2026-10-01T10:00:00Z',
    ...overrides,
  }
}

function renderCard(role: 'student' | 'teacher', locale = 'en', messages: typeof en = en) {
  const errors = vi.fn()
  render(
    <NextIntlClientProvider locale={locale} messages={messages} onError={errors}>
      <ClassroomsCard role={role} span={4} />
    </NextIntlClientProvider>,
  )
  return errors
}

beforeEach(() => vi.clearAllMocks())

describe('a student', () => {
  it('sees their classes, each a link, and no "Not available yet"', async () => {
    listSpaces.mockResolvedValue({ spaces: [space(1), space(2)] })
    renderCard('student')
    const link = await screen.findByRole('link', { name: /Physics 11-1/ }, LOADED)
    expect(link).toHaveAttribute('href', `/classroom/${space(1).id}`)
    expect(
      screen.getByRole('link', { name: en.dashboard.cards.allClassrooms }),
    ).toHaveAttribute('href', '/classroom')
    expect(screen.queryByText(en.dashboard.notYetAvailable)).toBeNull()
  })

  it('is told how to join when there is no class yet', async () => {
    listSpaces.mockResolvedValue({ spaces: [] })
    renderCard('student')
    expect(
      await screen.findByText(en.dashboard.cards.classesEmptyStudent, {}, LOADED),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: en.dashboard.cards.joinClass })).toHaveAttribute(
      'href',
      '/classroom',
    )
  })
})

describe('a teacher', () => {
  it('sees at most three active classrooms, with their member counts', async () => {
    listSpaces.mockResolvedValue({
      spaces: [
        space(1, { viewer_role: 'owner', member_count: 1 }),
        space(2, { viewer_role: 'owner', member_count: 24, status: 'archived' }),
        space(3, { viewer_role: 'owner', member_count: 30 }),
        space(4, { viewer_role: 'owner', member_count: 12 }),
        space(5, { viewer_role: 'owner', member_count: 8 }),
      ],
    })
    renderCard('teacher')
    const list = await screen.findByRole('list', {}, LOADED)
    const items = within(list).getAllByRole('link')
    expect(items.map((a) => a.getAttribute('href'))).toEqual([
      `/teacher/classroom/${space(1).id}`,
      `/teacher/classroom/${space(3).id}`,
      `/teacher/classroom/${space(4).id}`,
    ])
    expect(within(list).getByText('1 student')).toBeInTheDocument()
    expect(within(list).getByText('30 students')).toBeInTheDocument()
    // The archived one is not among the three; "All classrooms" still reaches it.
    expect(screen.queryByText('Physics 11-2')).toBeNull()
  })

  it('is offered the first classroom when there is none', async () => {
    listSpaces.mockResolvedValue({ spaces: [] })
    renderCard('teacher')
    expect(
      await screen.findByRole('link', { name: en.dashboard.cards.createClassroom }, LOADED),
    ).toHaveAttribute('href', '/teacher/classroom')
  })
})

describe('when the list cannot be loaded', () => {
  it('still offers the way in, and never says the feature is unavailable', async () => {
    listSpaces.mockRejectedValue(new Error('network'))
    renderCard('student')
    expect(
      await screen.findByRole('link', { name: en.dashboard.cards.allClassrooms }, LOADED),
    ).toHaveAttribute('href', '/classroom')
    expect(screen.queryByText(en.dashboard.notYetAvailable)).toBeNull()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])(
    'renders both roles, full and empty, in %s with no missing keys',
    async (locale, messages) => {
      const m = messages as typeof en
      listSpaces.mockResolvedValue({
        spaces: [space(1, { viewer_role: 'owner', member_count: 3 })],
      })
      const full = renderCard('teacher', locale, m)
      await screen.findByRole('list', {}, LOADED)
      expect(full).not.toHaveBeenCalled()
      listSpaces.mockResolvedValue({ spaces: [] })
      const empty = renderCard('student', locale, m)
      await screen.findByText(m.dashboard.cards.classesEmptyStudent, {}, LOADED)
      expect(empty).not.toHaveBeenCalled()
    },
  )
})
