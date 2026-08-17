import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import type { EnumsResponse } from '@/lib/api/types'
import { StudentSignupForm } from './StudentSignupForm'

/**
 * A LOCAL FIXTURE, not an import from the mock layer.
 *
 * This used to come from `lib/api/mock/db`, which was deleted when the mock
 * layer went (phase 1b). Inlining it here is the right home anyway: a test
 * fixture belongs beside the test that uses it, and importing one out of
 * application code meant a change to the fake could silently change what this
 * file asserts.
 *
 * The shape mirrors `GET /reference/enums` (tdd.md §3.1). Note that
 * `groups_by_class` is keyed by STRINGS while `class_levels` holds NUMBERS —
 * that is the contract, and the trap `TestClassLevelKeys` below pins.
 */
const ENUMS: EnumsResponse = {
  boards: [
    { code: 'PCTB', name: 'Punjab Curriculum and Textbook Board' },
    { code: 'STBB', name: 'Sindh Textbook Board' },
  ],
  class_levels: [9, 10, 11, 12],
  groups_by_class: {
    '9': [
      { code: 'science', label: 'Science' },
      { code: 'computer', label: 'Computer Science' },
    ],
    '10': [
      { code: 'science', label: 'Science' },
      { code: 'computer', label: 'Computer Science' },
    ],
    '11': [
      { code: 'pre_medical', label: 'Pre-Medical' },
      { code: 'pre_engineering', label: 'Pre-Engineering' },
      { code: 'ics', label: 'ICS' },
    ],
    '12': [
      { code: 'pre_medical', label: 'Pre-Medical' },
      { code: 'pre_engineering', label: 'Pre-Engineering' },
      { code: 'ics', label: 'ICS' },
    ],
  },
  mediums: ['en', 'ur'],
  languages: ['en', 'ur', 'roman_ur'],
}

const push = vi.fn()
const registerAccount = vi.fn()

vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/api/endpoints', () => ({ register: (...a: unknown[]) => registerAccount(...a) }))
vi.mock('@/components/auth/Turnstile', () => ({
  Turnstile: ({
    onVerify,
  }: {
    onVerify: (token: string) => void
    onExpired?: () => void
    resetNonce?: number
  }) => <button type="button" data-testid="turnstile" onClick={() => onVerify('mock-token')} />,
}))

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

/** Walks through to the review step and solves the security check. */
async function completeAcademicStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('radio', { name: /PCTB/ }))
  await user.click(screen.getByRole('radio', { name: 'Class 11' }))
  await user.click(screen.getByRole('radio', { name: 'ICS' }))
  await pickMedium(user)
  await user.click(screen.getByRole('button', { name: en.signup.common.continue }))
  await user.click(screen.getByTestId('turnstile'))
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
  it('keeps submit disabled on the review step until the captcha is solved', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)
    await user.click(screen.getByRole('radio', { name: /PCTB/ }))
    await user.click(screen.getByRole('radio', { name: 'Class 11' }))
    await user.click(screen.getByRole('radio', { name: 'ICS' }))
    await pickMedium(user)
    await user.click(screen.getByRole('button', { name: en.signup.common.continue }))

    expect(screen.getByRole('button', { name: en.signup.common.submit })).toBeDisabled()

    await user.click(screen.getByTestId('turnstile'))
    expect(screen.getByRole('button', { name: en.signup.common.submit })).toBeEnabled()
  })

  it('sends the class level as a number and the group alongside it', async () => {
    const user = userEvent.setup()
    renderForm()
    await completeBasicStep(user)
    await completeAcademicStep(user)
    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))

    expect(registerAccount).toHaveBeenCalledTimes(1)
    const body = registerAccount.mock.calls[0]?.[0]
    expect(body).toMatchObject({
      role: 'student',
      board: 'PCTB',
      class_level: 11,
      student_group: 'ics',
      medium: 'en',
      turnstile_token: 'mock-token',
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
    await user.click(screen.getByTestId('turnstile'))
    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))

    expect(push).toHaveBeenCalledWith('/onboarding/email')
  })
})

/**
 * Rehomed from `lib/api/mock/db.test.ts` when the mock layer was deleted
 * (phase 1b). The rest of that file tested the mock's own duplicate of the
 * onboarding derivation — a second implementation of a backend rule, and no
 * loss when both went. THIS trap is different: it is real in production code,
 * because `StudentSignupForm` indexes `groups_by_class` with a value drawn from
 * `class_levels`, and the two are different types by contract.
 */
describe('the class-level key trap', () => {
  it('pins where the string/number mismatch actually bites', () => {
    // Bracket access is SAFE: JavaScript coerces the key, so both forms are the
    // same lookup. COMPARISON is where it silently fails, in both directions --
    // which is what signup has to normalise around.
    const keys = Object.keys(ENUMS.groups_by_class)
    const nine = ENUMS.class_levels[0]

    expect(ENUMS.groups_by_class[9 as unknown as string]).toEqual(ENUMS.groups_by_class['9'])
    expect(keys.includes(nine as unknown as string)).toBe(false)
    expect(new Set(keys).has(nine as unknown as string)).toBe(false)
    expect(ENUMS.class_levels.includes('9' as unknown as number)).toBe(false)

    // The safe form.
    expect(keys.includes(String(nine))).toBe(true)
  })

  it('offers groups for every advertised class level', () => {
    for (const level of ENUMS.class_levels) {
      expect(ENUMS.groups_by_class[String(level)]?.length ?? 0).toBeGreaterThan(0)
    }
  })
})
