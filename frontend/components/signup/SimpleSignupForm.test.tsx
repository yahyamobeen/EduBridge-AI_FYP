import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { SimpleSignupForm } from './SimpleSignupForm'

const push = vi.fn()
const registerAccount = vi.fn()

vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/api/endpoints', () => ({ register: (...a: unknown[]) => registerAccount(...a) }))

function renderForm(role: 'teacher' | 'parent' = 'teacher') {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SimpleSignupForm role={role} />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  push.mockReset()
  registerAccount.mockReset()
  registerAccount.mockResolvedValue({ onboarding_state: 'email_verification_pending' })
})

describe('confirm password', () => {
  it('will not submit until passwords match', async () => {
    const user = userEvent.setup()
    renderForm('teacher')

    const submit = screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })
    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password124')
    expect(screen.getByText(en.signup.common.mismatch)).toBeInTheDocument()
    expect(submit).toBeDisabled()

    await user.clear(screen.getByLabelText(en.signup.common.confirmPassword))
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
    expect(submit).toBeEnabled()
  })

  it('gates only on length and match, leaving real policy to server', async () => {
    const user = userEvent.setup()
    renderForm('parent')

    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'alllowercase')
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'alllowercase')

    expect(screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })).toBeEnabled()
  })
})