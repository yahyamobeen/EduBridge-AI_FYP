import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { AssignmentDetail, AssignmentSummary } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { ClassworkTab } from './ClassworkTab'

/**
 * Classwork. What must hold: a member sees the server's status for each
 * assignment and no create control; the owner creates with points as a number,
 * a due date as an ISO instant carrying an offset, and an optional chapter;
 * out-of-range points never reach the server; a refusal is explained by its
 * field, never by `message`.
 */

const listAssignments = vi.fn()
const createAssignment = vi.fn()
const getAssignment = vi.fn()
const listChapters = vi.fn()
const listSubmissions = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  listAssignments: (...a: unknown[]) => listAssignments(...a),
  createAssignment: (...a: unknown[]) => createAssignment(...a),
  getAssignment: (...a: unknown[]) => getAssignment(...a),
  listChapters: (...a: unknown[]) => listChapters(...a),
  listSubmissions: (...a: unknown[]) => listSubmissions(...a),
}))

const LOADED = { timeout: 5_000 }

function summary(overrides: Partial<AssignmentSummary> = {}): AssignmentSummary {
  return {
    id: 'as-1',
    title: 'Lab 1',
    due_at: '2026-10-10T12:00:00Z',
    points: 10,
    chapter: null,
    publish_at: '2026-10-04T09:00:00Z',
    scheduled: false,
    my_status: null,
    my_grade: null,
    turned_in_count: null,
    ...overrides,
  }
}

function detail(overrides: Partial<AssignmentDetail> = {}): AssignmentDetail {
  return {
    ...summary(),
    space_id: 'space-1',
    instructions: 'Measure g.',
    created_at: '2026-10-04T09:00:00Z',
    updated_at: '2026-10-04T09:00:00Z',
    my_submission: null,
    ...overrides,
  }
}

function renderTab(
  props: Partial<React.ComponentProps<typeof ClassworkTab>> = {},
  locale = 'en',
  messages: typeof en = en,
  onError?: () => void,
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      {...(onError ? { onError } : {})}
    >
      <ClassworkTab
        spaceId="space-1"
        subjectId="subject-1"
        isOwner={false}
        canPost={false}
        {...props}
      />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listChapters.mockResolvedValue({
    chapters: [{ id: 'ch-1', number: 3, title: 'Motion' }],
  })
  listSubmissions.mockResolvedValue({ rows: [] })
})

describe('a member', () => {
  it("sees the server's status for each assignment, and no create control", async () => {
    listAssignments.mockResolvedValue({
      items: [summary({ my_status: 'missing' })],
      next_cursor: null,
    })
    renderTab()
    expect(await screen.findByText(en.classroom.status.missing, {}, LOADED)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: en.classroom.classwork.create })).toBeNull()
  })

  it('opens an assignment and comes back to the list', async () => {
    listAssignments.mockResolvedValue({ items: [summary()], next_cursor: null })
    getAssignment.mockResolvedValue(
      detail({
        my_status: 'assigned',
        my_submission: {
          body: '',
          link_url: null,
          turned_in_at: null,
          status: 'assigned',
          grade: null,
          feedback: null,
          returned_at: null,
        },
      }),
    )
    renderTab()
    await userEvent.click(await screen.findByRole('button', { name: /Lab 1/ }, LOADED))
    expect(getAssignment).toHaveBeenCalledWith('as-1', expect.any(AbortSignal))
    expect(await screen.findByText('Measure g.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: en.classroom.submission.heading })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: en.classroom.assignment.back }))
    expect(await screen.findByRole('button', { name: /Lab 1/ })).toBeInTheDocument()
  })
})

describe('the owner', () => {
  beforeEach(() => {
    listAssignments.mockResolvedValue({ items: [], next_cursor: null })
  })

  it('creates with numeric points, an ISO due date and a chapter', async () => {
    createAssignment.mockResolvedValue(
      detail({ id: 'as-9', title: 'Lab 2', turned_in_count: 0 }),
    )
    renderTab({ isOwner: true, canPost: true })
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.classwork.create }, LOADED),
    )
    await userEvent.type(screen.getByLabelText(en.classroom.assignment.titleLabel), ' Lab 2 ')
    await userEvent.type(screen.getByLabelText(en.classroom.assignment.pointsLabel), '20')
    await userEvent.type(
      screen.getByLabelText(en.classroom.assignment.dueLabel),
      '2030-01-01T10:00',
    )
    const chapter = screen.getByLabelText(en.classroom.assignment.chapterLabel)
    await waitFor(() => expect(chapter).toBeEnabled())
    await userEvent.selectOptions(chapter, 'ch-1')
    await userEvent.click(screen.getByRole('button', { name: en.classroom.assignment.create }))

    const [spaceId, body] = createAssignment.mock.calls[0]!
    expect(spaceId).toBe('space-1')
    expect(body).toMatchObject({ title: 'Lab 2', points: 20, chapter_id: 'ch-1' })
    expect(body.due_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    expect(body).not.toHaveProperty('publish_at')
    expect(await screen.findByRole('button', { name: /Lab 2/ })).toBeInTheDocument()
  })

  it('never sends points out of range', async () => {
    renderTab({ isOwner: true, canPost: true })
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.classwork.create }, LOADED),
    )
    await userEvent.type(screen.getByLabelText(en.classroom.assignment.titleLabel), 'Lab')
    await userEvent.type(screen.getByLabelText(en.classroom.assignment.pointsLabel), '0')
    expect(screen.getByText(en.classroom.assignment.pointsInvalid)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: en.classroom.assignment.create })).toBeDisabled()
  })

  it('explains a refused due date by its field', async () => {
    createAssignment.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { fields: { due_at: 'too early' } }),
    )
    renderTab({ isOwner: true, canPost: true })
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.classwork.create }, LOADED),
    )
    await userEvent.type(screen.getByLabelText(en.classroom.assignment.titleLabel), 'Lab')
    await userEvent.click(screen.getByRole('button', { name: en.classroom.assignment.create }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      en.classroom.assignment.dueInvalid,
    )
  })

  it('cannot create in an archived classroom, and is told why', async () => {
    renderTab({ isOwner: true, canPost: false })
    expect(
      await screen.findByText(en.classroom.classwork.archivedNoPosting, {}, LOADED),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: en.classroom.classwork.create })).toBeNull()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])(
    'renders the owner list and form fully in %s with no missing keys',
    async (locale, messages) => {
      const onError = vi.fn()
      listAssignments.mockResolvedValue({
        items: [
          summary({
            scheduled: true,
            turned_in_count: 3,
            chapter: { id: 'ch-1', number: 3, title: 'Motion' },
          }),
          summary({ id: 'as-2', due_at: null, points: null, turned_in_count: 0 }),
        ],
        next_cursor: 'more',
      })
      renderTab({ isOwner: true, canPost: true }, locale, messages as typeof en, onError)
      const create = (messages as typeof en).classroom.classwork.create
      await userEvent.click(await screen.findByRole('button', { name: create }, LOADED))
      await waitFor(() => expect(listChapters).toHaveBeenCalled())
      expect(onError).not.toHaveBeenCalled()
    },
  )
})
