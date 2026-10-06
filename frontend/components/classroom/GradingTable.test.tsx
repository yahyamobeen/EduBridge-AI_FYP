import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssignmentDetail, StudentWork, SubmissionRow } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { GradingTable } from './GradingTable'

/**
 * The teacher's table. What must hold: every active member is listed, turned
 * in or not; a student's draft is never shown ("not turned in yet" is all the
 * server reveals); a grade above the points never reaches the server; "Save
 * and return" sends `return_to_student: true` and the row updates in place.
 */

const listSubmissions = vi.fn()
const getStudentWork = vi.fn()
const saveGrade = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  listSubmissions: (...a: unknown[]) => listSubmissions(...a),
  getStudentWork: (...a: unknown[]) => getStudentWork(...a),
  saveGrade: (...a: unknown[]) => saveGrade(...a),
}))

const LOADED = { timeout: 5_000 }

const ASSIGNMENT: AssignmentDetail = {
  id: 'as-1',
  title: 'Lab 1',
  due_at: '2026-10-10T12:00:00Z',
  points: 10,
  chapter: null,
  publish_at: '2026-10-04T09:00:00Z',
  scheduled: false,
  my_status: null,
  my_grade: null,
  turned_in_count: 1,
  space_id: 'space-1',
  instructions: '',
  created_at: '2026-10-04T09:00:00Z',
  updated_at: '2026-10-04T09:00:00Z',
  my_submission: null,
  attachments: [],
}

function row(overrides: Partial<SubmissionRow> = {}): SubmissionRow {
  return {
    student_id: 'st-1',
    full_name: 'Aisha Khan',
    status: 'turned_in',
    turned_in_at: '2026-10-05T09:00:00Z',
    grade: null,
    returned_at: null,
    graded: false,
    ...overrides,
  }
}

function work(overrides: Partial<StudentWork> = {}): StudentWork {
  return { ...row(), body: 'g = 9.8', feedback: '', files: [], links: [], ...overrides }
}

function renderTable(canGrade = true, locale = 'en', messages: typeof en = en) {
  const errors = vi.fn()
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      onError={errors}
    >
      <GradingTable assignment={ASSIGNMENT} canGrade={canGrade} />
    </NextIntlClientProvider>,
  )
  return errors
}

beforeEach(() => {
  vi.clearAllMocks()
  listSubmissions.mockResolvedValue({
    rows: [
      row(),
      row({
        student_id: 'st-2',
        full_name: 'Bilal Ahmed',
        status: 'missing',
        turned_in_at: null,
      }),
    ],
  })
  getStudentWork.mockResolvedValue(work())
})

async function review(name: string) {
  const item = (await screen.findByText(name, {}, LOADED)).closest('li')!
  await userEvent.click(within(item).getByRole('button', { name: en.classroom.grading.review }))
  return item
}

describe('the table', () => {
  it('lists every member and how many turned in', async () => {
    renderTable()
    expect(await screen.findByText('1 of 2 turned in', {}, LOADED)).toBeInTheDocument()
    expect(screen.getByText(en.classroom.status.missing)).toBeInTheDocument()
  })

  it('never shows a draft — only that nothing is turned in', async () => {
    getStudentWork.mockResolvedValue(
      work({ turned_in_at: null, body: null, status: 'missing' }),
    )
    renderTable()
    const item = await review('Bilal Ahmed')
    expect(await within(item).findByText(en.classroom.grading.notTurnedIn)).toBeInTheDocument()
  })

  it("shows the student's files and links, read-only", async () => {
    getStudentWork.mockResolvedValue(
      work({
        files: [
          {
            id: 'f-1',
            filename: 'Lab report.pdf',
            content_type: 'application/pdf',
            size_bytes: 2_000,
            created_at: '2026-10-05T08:00:00Z',
          },
        ],
        links: [
          { id: 'l-1', url: 'https://example.com/lab', created_at: '2026-10-05T08:30:00Z' },
        ],
      }),
    )
    renderTable()
    const item = await review('Aisha Khan')
    const link = await within(item).findByRole('link', { name: 'https://example.com/lab' })
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(
      within(item).getByRole('button', { name: 'View Lab report.pdf' }),
    ).toBeInTheDocument()
    // The teacher cannot add to or remove from a student's work.
    expect(within(item).queryByRole('button', { name: en.classroom.files.addMenu })).toBeNull()
    expect(within(item).queryByRole('button', { name: /^Remove/ })).toBeNull()
  })
})

describe('grading', () => {
  it('saves and returns, and the row updates in place', async () => {
    saveGrade.mockResolvedValue(
      work({
        grade: 9,
        feedback: 'Well done',
        graded: true,
        returned_at: '2026-10-06T09:00:00Z',
        status: 'graded',
      }),
    )
    renderTable()
    const item = await review('Aisha Khan')
    await userEvent.type(await within(item).findByLabelText('Grade (out of 10)'), '9')
    await userEvent.type(
      within(item).getByLabelText(en.classroom.grading.feedbackLabel),
      ' Well done ',
    )
    await userEvent.click(
      within(item).getByRole('button', { name: en.classroom.grading.saveAndReturn }),
    )
    expect(saveGrade).toHaveBeenCalledWith('as-1', 'st-1', {
      grade: 9,
      feedback: 'Well done',
      return_to_student: true,
    })
    expect(await within(item).findByText(en.classroom.grading.returned)).toBeInTheDocument()
    expect(within(item).getByText('9 / 10')).toBeInTheDocument()
  })

  it('never sends a grade above the points', async () => {
    renderTable()
    const item = await review('Aisha Khan')
    await userEvent.type(await within(item).findByLabelText('Grade (out of 10)'), '11')
    await userEvent.click(within(item).getByRole('button', { name: en.classroom.grading.save }))
    expect(saveGrade).not.toHaveBeenCalled()
    expect(within(item).getByRole('alert')).toHaveTextContent(
      'The grade must be between 0 and 10.',
    )
  })

  it('offers no grading in an archived classroom', async () => {
    renderTable(false)
    expect(
      await screen.findByText(en.classroom.grading.archivedNoGrading, {}, LOADED),
    ).toBeInTheDocument()
    const item = await review('Aisha Khan')
    expect(await within(item).findByText('g = 9.8')).toBeInTheDocument()
    expect(within(item).queryByRole('button', { name: en.classroom.grading.save })).toBeNull()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])(
    'renders the table and a review fully in %s with no missing keys',
    async (locale, messages) => {
      listSubmissions.mockResolvedValue({
        rows: [
          row({
            grade: 8,
            graded: true,
            returned_at: '2026-10-06T09:00:00Z',
            status: 'graded',
          }),
        ],
      })
      getStudentWork.mockResolvedValue(
        work({
          links: [
            { id: 'l-1', url: 'https://example.com/lab', created_at: '2026-10-05T08:30:00Z' },
          ],
        }),
      )
      const errors = renderTable(true, locale, messages as typeof en)
      const m = messages as typeof en
      const item = (await screen.findByText('Aisha Khan', {}, LOADED)).closest('li')!
      await userEvent.click(
        within(item).getByRole('button', { name: m.classroom.grading.review }),
      )
      expect(await within(item).findByText('g = 9.8')).toBeInTheDocument()
      expect(errors).not.toHaveBeenCalled()
    },
  )
})
