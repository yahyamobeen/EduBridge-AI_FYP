import { render, screen, within } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ParentChild, ParentOverviewResponse } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { ParentOverview } from './ParentClassrooms'

/**
 * The parent's overview (prd.md CL-10). What must hold: each child, their
 * classrooms and teachers, each deadline with its status, and a grade only as
 * the server sends it (once returned); the page says what it never shows; and
 * it offers NOTHING to click — no link into a classroom, no tab, no button —
 * because the parent surface is read-only.
 */

const getParentClassrooms = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  getParentClassrooms: (...a: unknown[]) => getParentClassrooms(...a),
}))

const LOADED = { timeout: 5_000 }
const p = en.classroom.parent

function child(overrides: Partial<ParentChild> = {}): ParentChild {
  return {
    student_id: 's-1',
    full_name: 'Ayesha Khan',
    classrooms: [
      {
        space_id: 'sp-1',
        title: 'Physics 11-A',
        status: 'active',
        subject_name: 'Physics',
        teacher_name: 'Sir Ahmed',
        assignments: [
          {
            id: 'a-1',
            title: 'Lab 1',
            due_at: '2026-10-07T07:00:00Z',
            points: 10,
            status: 'graded',
            grade: 8.5,
          },
          {
            id: 'a-2',
            title: 'Worksheet',
            due_at: null,
            points: null,
            status: 'missing',
            grade: null,
          },
        ],
      },
    ],
    ...overrides,
  }
}

function renderOverview(
  data: ParentOverviewResponse | Error,
  locale = 'en',
  messages: typeof en = en,
  onError?: () => void,
) {
  if (data instanceof Error) getParentClassrooms.mockRejectedValue(data)
  else getParentClassrooms.mockResolvedValue(data)
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      {...(onError ? { onError } : {})}
    >
      <ParentOverview />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('the overview', () => {
  it('shows each child, their classroom and teacher, deadlines, status and a returned grade', async () => {
    renderOverview({ children: [child()] })
    expect(
      await screen.findByRole('heading', { name: 'Ayesha Khan' }, LOADED),
    ).toBeInTheDocument()
    const room = screen.getByRole('heading', { name: 'Physics 11-A' }).closest('section')!
    expect(within(room).getByText('Physics · Sir Ahmed')).toBeInTheDocument()
    const lab = within(room).getByText('Lab 1').closest('li')!
    expect(within(lab).getByText(en.classroom.status.graded)).toBeInTheDocument()
    expect(within(lab).getByText('8.5 / 10')).toBeInTheDocument()
    expect(within(lab).getByText(/^Due /)).toBeInTheDocument()
    const sheet = within(room).getByText('Worksheet').closest('li')!
    expect(within(sheet).getByText(en.classroom.status.missing)).toBeInTheDocument()
    expect(within(sheet).getByText(p.noDue)).toBeInTheDocument()
  })

  it('says what it never shows', async () => {
    renderOverview({ children: [child()] })
    expect(await screen.findByText(p.privacy, {}, LOADED)).toBeInTheDocument()
  })

  it('offers nothing to click: no link into a classroom, no tab, no button', async () => {
    renderOverview({ children: [child()] })
    await screen.findByText('Lab 1', {}, LOADED)
    expect(screen.queryAllByRole('link')).toEqual([])
    expect(screen.queryAllByRole('button')).toEqual([])
    expect(screen.queryAllByRole('tab')).toEqual([])
  })

  it('labels an archived classroom', async () => {
    const archived = child()
    archived.classrooms[0]!.status = 'archived'
    renderOverview({ children: [archived] })
    expect(await screen.findByText(p.archived, {}, LOADED)).toBeInTheDocument()
  })

  it('says when a classroom has nothing current', async () => {
    const quiet = child()
    quiet.classrooms[0]!.assignments = []
    renderOverview({ children: [quiet] })
    expect(await screen.findByText(p.noAssignments, {}, LOADED)).toBeInTheDocument()
  })

  it('names a linked child who is in no classroom yet', async () => {
    renderOverview({ children: [child({ full_name: 'Bilal', classrooms: [] })] })
    expect(
      await screen.findByText('Bilal is not in a classroom yet.', {}, LOADED),
    ).toBeInTheDocument()
  })

  it('explains what to do when no child is linked', async () => {
    renderOverview({ children: [] })
    expect(await screen.findByText(p.noChildren, {}, LOADED)).toBeInTheDocument()
  })

  it('says so when the overview cannot be loaded', async () => {
    renderOverview(new TypeError('offline'))
    expect(await screen.findByText(p.unavailable, {}, LOADED)).toBeInTheDocument()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders fully in %s with no missing keys', async (locale, messages) => {
    const onError = vi.fn()
    const busy = child()
    busy.classrooms[0]!.status = 'archived'
    renderOverview(
      { children: [busy, child({ student_id: 's-2', full_name: 'Bilal', classrooms: [] })] },
      locale,
      messages as typeof en,
      onError,
    )
    await screen.findByText('Lab 1', {}, LOADED)
    expect(onError).not.toHaveBeenCalled()
  })
})
