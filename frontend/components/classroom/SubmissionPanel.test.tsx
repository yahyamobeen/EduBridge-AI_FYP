import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { AssignmentDetail, MySubmission } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { SubmissionPanel } from './SubmissionPanel'

/**
 * A student's own work. What must hold: unsaved edits go in WITH the turn-in,
 * not lost behind it; a server refusal gets its own message, chosen by
 * `details`, never by `message`; a returned grade shows with its feedback; and
 * attached files and links make it a turn-in, not "Mark as done". Adding and
 * removing files and links is `WorkAttachments.test.tsx`.
 */

const saveSubmission = vi.fn()
const turnInSubmission = vi.fn()
const unsubmitSubmission = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  saveSubmission: (...a: unknown[]) => saveSubmission(...a),
  turnInSubmission: (...a: unknown[]) => turnInSubmission(...a),
  unsubmitSubmission: (...a: unknown[]) => unsubmitSubmission(...a),
}))

function mine(overrides: Partial<MySubmission> = {}): MySubmission {
  return {
    body: '',
    turned_in_at: null,
    status: 'assigned',
    grade: null,
    feedback: null,
    returned_at: null,
    files: [],
    links: [],
    ...overrides,
  }
}

function assignment(sub: MySubmission): AssignmentDetail & { my_submission: MySubmission } {
  return {
    id: 'as-1',
    title: 'Lab 1',
    due_at: '2026-10-10T12:00:00Z',
    points: 10,
    chapter: null,
    publish_at: '2026-10-04T09:00:00Z',
    scheduled: false,
    my_status: sub.status,
    my_grade: sub.grade,
    turned_in_count: null,
    space_id: 'space-1',
    instructions: '',
    created_at: '2026-10-04T09:00:00Z',
    updated_at: '2026-10-04T09:00:00Z',
    my_submission: sub,
    attachments: [],
  }
}

const onChange = vi.fn()

function renderPanel(sub: MySubmission, locale = 'en', messages: typeof en = en) {
  const errors = vi.fn()
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      onError={errors}
    >
      <SubmissionPanel assignment={assignment(sub)} onChange={onChange} />
    </NextIntlClientProvider>,
  )
  return errors
}

beforeEach(() => vi.clearAllMocks())

describe('editing', () => {
  it('saves unsaved work before turning it in', async () => {
    saveSubmission.mockResolvedValue(mine({ body: 'My answer' }))
    turnInSubmission.mockResolvedValue(
      mine({ body: 'My answer', turned_in_at: '2026-10-05T09:00:00Z', status: 'turned_in' }),
    )
    renderPanel(mine())
    await userEvent.type(screen.getByLabelText(en.classroom.submission.bodyLabel), 'My answer')
    await userEvent.click(screen.getByRole('button', { name: en.classroom.submission.turnIn }))
    expect(saveSubmission).toHaveBeenCalledWith('as-1', { body: 'My answer' })
    expect(turnInSubmission).toHaveBeenCalledWith('as-1')
    expect(saveSubmission.mock.invocationCallOrder[0]).toBeLessThan(
      turnInSubmission.mock.invocationCallOrder[0]!,
    )
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'turned_in' }))
  })

  it('offers "Mark as done" when there is nothing to hand in', () => {
    renderPanel(mine())
    expect(screen.getByRole('button', { name: en.classroom.submission.markDone })).toBeEnabled()
  })

  it('turns in work that carries only a link: it is not "Mark as done"', () => {
    renderPanel(
      mine({
        links: [
          { id: 'l-1', url: 'https://example.com/lab', created_at: '2026-10-05T09:00:00Z' },
        ],
      }),
    )
    expect(screen.getByRole('button', { name: en.classroom.submission.turnIn })).toBeEnabled()
    expect(screen.queryByRole('button', { name: en.classroom.submission.markDone })).toBeNull()
  })

  it('offers the "+ Add" menu while the work is a draft', () => {
    renderPanel(mine())
    expect(screen.getByRole('button', { name: en.classroom.files.addMenu })).toHaveAttribute(
      'aria-haspopup',
      'menu',
    )
  })
})

describe('turned in', () => {
  it('says the work is locked once the teacher has started grading', async () => {
    unsubmitSubmission.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { reason: 'graded' }),
    )
    renderPanel(
      mine({ body: 'Done', turned_in_at: '2026-10-05T09:00:00Z', status: 'turned_in' }),
    )
    expect(screen.queryByLabelText(en.classroom.submission.bodyLabel)).toBeNull()
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.submission.unsubmit }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(en.classroom.submission.locked)
  })
})

describe('returned', () => {
  it('shows the grade and the private feedback, and links only https', () => {
    renderPanel(
      mine({
        body: 'Done',
        links: [
          { id: 'l-1', url: 'https://example.com/lab', created_at: '2026-10-05T08:00:00Z' },
        ],
        turned_in_at: '2026-10-05T09:00:00Z',
        returned_at: '2026-10-06T09:00:00Z',
        status: 'graded',
        grade: 8.5,
        feedback: 'Show your units.',
      }),
    )
    expect(screen.getByText('Grade: 8.5 / 10')).toBeInTheDocument()
    expect(screen.getByText('Show your units.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'https://example.com/lab' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(screen.queryByRole('button', { name: en.classroom.submission.unsubmit })).toBeNull()
    // Returned work is read-only: nothing to add, nothing to remove.
    expect(screen.queryByRole('button', { name: en.classroom.files.addMenu })).toBeNull()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders every state fully in %s with no missing keys', (locale, messages) => {
    const states = [
      mine(),
      mine({ body: 'x', turned_in_at: '2026-10-05T09:00:00Z', status: 'turned_in_late' }),
      mine({
        body: 'x',
        turned_in_at: '2026-10-05T09:00:00Z',
        returned_at: '2026-10-06T09:00:00Z',
        status: 'graded',
        grade: 7,
        feedback: 'Good',
      }),
    ]
    for (const state of states) {
      const errors = renderPanel(state, locale, messages as typeof en)
      expect(errors).not.toHaveBeenCalled()
    }
  })
})
