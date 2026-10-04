import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import en from '@/messages/en.json'
import { CreateClassForm } from './CreateClassForm'

/**
 * Creating a classroom. Subjects belong to one (board, class) pair, so the list
 * must come from the API for exactly the pair chosen — never a literal list —
 * and a change of either must discard a subject chosen under the old pair.
 */

const push = vi.fn()
vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}))

const listSubjects = vi.fn()
const createSpace = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  getEnums: () =>
    Promise.resolve({
      boards: [
        { code: 'PCTB', name: 'Punjab Curriculum and Textbook Board' },
        { code: 'STBB', name: 'Sindh Textbook Board' },
      ],
      class_levels: [9, 10, 11, 12],
      groups_by_class: {},
      mediums: [],
      languages: [],
    }),
  listSubjects: (...a: unknown[]) => listSubjects(...a),
  createSpace: (...a: unknown[]) => createSpace(...a),
}))

function renderForm() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <CreateClassForm />
    </NextIntlClientProvider>,
  )
}

async function choose(board: string, level: string) {
  await userEvent.selectOptions(
    await screen.findByLabelText(en.classroom.create.boardLabel),
    board,
  )
  await userEvent.selectOptions(screen.getByLabelText(en.classroom.create.classLabel), level)
}

beforeEach(() => {
  vi.clearAllMocks()
  listSubjects.mockResolvedValue({
    subjects: [
      { id: 'sub-phy', name: 'Physics', groups: ['science'] },
      { id: 'sub-chem', name: 'Chemistry', groups: ['science'] },
    ],
  })
})

describe('CreateClassForm', () => {
  it('asks the API for the subjects of exactly the chosen board and class', async () => {
    renderForm()
    await choose('PCTB', '9')
    expect(listSubjects).toHaveBeenLastCalledWith('PCTB', 9, expect.any(AbortSignal))
    expect(await screen.findByRole('option', { name: 'Physics' })).toBeInTheDocument()
  })

  it('creates the classroom and opens it', async () => {
    createSpace.mockResolvedValue({ id: 'space-9' })
    renderForm()
    await choose('PCTB', '9')
    await userEvent.selectOptions(
      screen.getByLabelText(en.classroom.create.subjectLabel),
      await screen.findByRole('option', { name: 'Physics' }),
    )
    await userEvent.type(
      screen.getByLabelText(en.classroom.create.titleLabel),
      '  Physics 9-A ',
    )
    await userEvent.click(screen.getByRole('button', { name: en.classroom.create.submit }))
    expect(createSpace).toHaveBeenCalledWith({ title: 'Physics 9-A', subject_id: 'sub-phy' })
    expect(push).toHaveBeenCalledWith('/teacher/classroom/space-9')
  })

  it('discards the chosen subject when the class changes', async () => {
    renderForm()
    await choose('PCTB', '9')
    const subject = screen.getByLabelText(en.classroom.create.subjectLabel)
    await userEvent.selectOptions(
      subject,
      await screen.findByRole('option', { name: 'Physics' }),
    )
    await userEvent.selectOptions(screen.getByLabelText(en.classroom.create.classLabel), '10')
    expect(subject).toHaveValue('')
  })

  it('explains the active-classroom limit', async () => {
    createSpace.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { reason: 'classroom_limit' }),
    )
    renderForm()
    await choose('PCTB', '9')
    await userEvent.selectOptions(
      screen.getByLabelText(en.classroom.create.subjectLabel),
      await screen.findByRole('option', { name: 'Physics' }),
    )
    await userEvent.type(screen.getByLabelText(en.classroom.create.titleLabel), 'P')
    await userEvent.click(screen.getByRole('button', { name: en.classroom.create.submit }))
    expect(await screen.findByRole('alert')).toHaveTextContent(en.classroom.create.limit)
    expect(push).not.toHaveBeenCalled()
  })
})
