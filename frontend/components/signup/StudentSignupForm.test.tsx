import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ENUMS } from '@/lib/api/mock/db'
import { StudentSignupForm } from './StudentSignupForm'

const push = vi.fn()
const registerAccount = vi.fn()

vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/api/endpoints', () => ({ register: (...a: unknown[]) => registerAccount(...a) }))

function renderForm() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <StudentSignupForm enums={ENUMS} />
    </NextIntlClientProvider>,
  )
}

/**
 * "English" appears as both a medium and an interface language, so every
 * radio query is scoped to its own fieldset.
 */
function inGroup(legend: string) {
  return within(screen.getByRole('group', { name: legend }))
}

const pickMedium = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(inGroup(en.signup.student.medium).getByRole('radio', { name: 'English' }))

async function completeBasicStep(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
  await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
  await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
  await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
  await user.click(screen.getByRole('button', { name: en.signup.common.continue }))
}

beforeEach(() => {
  push.mockReset()
  registerAccount.mockReset()
  registerAccount.mockResolvedValue({ onboarding_state: 'email_verification_pending' })
})

describe('step gating', () => {
  it('will not advance until the basic details are filled in', async () => {
    const user = userEvent.setup()
    renderForm()
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha')
    await user.type(screen.getByLabelText(en.signup.common.email), 'a@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeEnabled()
  })

  it('will not advance until passwords match', async () => {
    const user = userEvent.setup()
    renderForm()

    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password124')
    expect(screen.getByText(en.signup.common.mismatch)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

    await user.clear(screen.getByLabelText(en.signup.common.confirmPassword))
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeEnabled()
  })

  it('will not advance out of the academic step until a group is chosen', async () => {
    // This is what makes 422 INVALID_CLASS_GROUP unreachable through the UI.
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)

    await user.click(screen.getByRole('radio', { name: /PCTB/ }))
    await user.click(screen.getByRole('radio', { name: 'Class 9' }))
    await pickMedium(user)
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

    await user.click(screen.getByRole('radio', { name: 'Science' }))
    expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeEnabled()
  })
})

describe('class to group dependency', () => {
  it('offers only the groups belonging to the chosen class', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)

    await user.click(screen.getByRole('radio', { name: 'Class 9' }))
    expect(screen.getByRole('radio', { name: 'Science' })).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Pre-Medical' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'Class 11' }))
    expect(screen.getByRole('radio', { name: 'Pre-Medical' })).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Science' })).not.toBeInTheDocument()
  })

  it('clears the chosen group when the class changes', async () => {
    // Without this, 9 + science survives a switch to Class 11 and submits an
    // invalid pair that only the server would reject.
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)

    await user.click(screen.getByRole('radio', { name: 'Class 9' }))
    await user.click(screen.getByRole('radio', { name: 'Science' }))
    expect(screen.getByRole('radio', { name: 'Science' })).toBeChecked()

    await user.click(screen.getByRole('radio', { name: 'Class 11' }))
    for (const group of ['Pre-Medical', 'Pre-Engineering', 'ICS']) {
      expect(screen.getByRole('radio', { name: group })).not.toBeChecked()
    }
  })

  it('asks for a class before showing any group', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)
    expect(screen.getByText(en.signup.student.groupPickClassFirst)).toBeInTheDocument()
  })
})

describe('parental consent notice', () => {
  it.each([
    ['Class 9', true],
    ['Class 10', true],
    ['Class 11', false],
    ['Class 12', false],
  ])('%s shows the notice: %s', async (className, expected) => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)
    await user.click(screen.getByRole('radio', { name: className }))

    const notice = screen.queryByText(en.signup.student.consentTitle)
    if (expected) expect(notice).toBeInTheDocument()
    else expect(notice).not.toBeInTheDocument()
  })
})

describe('submission', () => {
  it('sends the class level as a number and the group alongside it', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)

    await user.click(screen.getByRole('radio', { name: /PCTB/ }))
    await user.click(screen.getByRole('radio', { name: 'Class 11' }))
    await user.click(screen.getByRole('radio', { name: 'ICS' }))
    await pickMedium(user)
    await user.click(screen.getByRole('button', { name: en.signup.common.continue }))
    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))

    expect(registerAccount).toHaveBeenCalledTimes(1)
    const body = registerAccount.mock.calls[0]?.[0]
    expect(body).toMatchObject({
      role: 'student',
      board: 'PCTB',
      // A string here would fail the contract, which types class_levels as numbers.
      class_level: 11,
      student_group: 'ics',
      medium: 'en',
    })
    expect(typeof body.class_level).toBe('number')
  })

  it('goes to email verification, because registration issues no session', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)
    await user.click(screen.getByRole('radio', { name: /PCTB/ }))
    await user.click(screen.getByRole('radio', { name: 'Class 9' }))
    await user.click(screen.getByRole('radio', { name: 'Science' }))
    await pickMedium(user)
    await user.click(screen.getByRole('button', { name: en.signup.common.continue }))
    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))

    expect(push).toHaveBeenCalledWith('/onboarding/email')
  })
})
