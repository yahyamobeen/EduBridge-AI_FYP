import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import en from '@/messages/en.json'
import { JoinClassForm } from './JoinClassForm'

/**
 * Joining a class. The refusal messages are the point: each catalogued
 * `details.reason` must reach the student as its own explanation, and a removed
 * student must get exactly the same words as a mistyped code (the server sends
 * the same reason, and nothing here may invent a difference).
 */

const push = vi.fn()
vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}))

const joinSpace = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  joinSpace: (...a: unknown[]) => joinSpace(...a),
}))

function renderForm() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <JoinClassForm />
    </NextIntlClientProvider>,
  )
}

async function enter(code: string) {
  await userEvent.type(screen.getByLabelText(en.classroom.join.label), code)
  await userEvent.click(screen.getByRole('button', { name: en.classroom.join.submit }))
}

beforeEach(() => vi.clearAllMocks())

describe('JoinClassForm', () => {
  it('stays disabled until eight letters or digits are entered', async () => {
    renderForm()
    const button = screen.getByRole('button', { name: en.classroom.join.submit })
    await userEvent.type(screen.getByLabelText(en.classroom.join.label), 'ab-cd')
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText(en.classroom.join.label), 'efgh')
    expect(button).toBeEnabled()
  })

  it('sends the normalised code and opens the class', async () => {
    joinSpace.mockResolvedValue({ space_id: 'space-1', already_member: false })
    renderForm()
    await enter('abcd-efgh')
    expect(joinSpace).toHaveBeenCalledWith('ABCDEFGH')
    expect(push).toHaveBeenCalledWith('/classroom/space-1')
  })

  it.each([
    ['invalid_code', en.classroom.join.invalid],
    ['classroom_full', en.classroom.join.full],
  ])('explains %s', async (reason, message) => {
    joinSpace.mockRejectedValue(new ApiError(400, 'VALIDATION_ERROR', 'x', { reason }))
    renderForm()
    await enter('ABCDEFGH')
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(push).not.toHaveBeenCalled()
  })

  it('names the class on a mismatch', async () => {
    joinSpace.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', {
        reason: 'class_mismatch',
        space: { title: 'P', subject_name: 'Physics', board: 'PCTB', class_level: 11 },
      }),
    )
    renderForm()
    await enter('ABCDEFGH')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This class is for Class 11 (PCTB) students',
    )
  })

  it('tells a gated student why, rather than failing generically', async () => {
    joinSpace.mockRejectedValue(new ApiError(403, 'GATE_PENDING', 'x'))
    renderForm()
    await enter('ABCDEFGH')
    expect(await screen.findByRole('alert')).toHaveTextContent(en.classroom.join.gatePending)
  })
})
