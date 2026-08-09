import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import { SimpleSignupForm } from './SimpleSignupForm'

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
  }) => (
    <button type="button" data-testid="turnstile" onClick={() => onVerify('mock-token')} />
  ),
}))

function renderForm(role: 'teacher' | 'parent' = 'teacher') {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SimpleSignupForm role={role} />
    </NextIntlClientProvider>,
  )
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(en.signup.common.fullName), 'Ayesha Teacher')
  await user.type(screen.getByLabelText(en.signup.common.email), 'ayesha@example.com')
  await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
  await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
  await user.click(screen.getByTestId('turnstile'))
  await user.click(screen.getByRole('button', { name: en.signup.common.submit }))
}

beforeEach(() => {
  push.mockReset()
  registerAccount.mockReset()
  registerAccount.mockResolvedValue({ onboarding_state: 'email_verification_pending' })
})

describe('SimpleSignupForm', () => {
  it('stays disabled until the captcha token exists', async () => {
    const user = userEvent.setup()
    renderForm()
    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Ayesha Teacher')
    await user.type(screen.getByLabelText(en.signup.common.email), 'ayesha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')

    expect(screen.getByRole('button', { name: en.signup.common.submit })).toBeDisabled()

    await user.click(screen.getByTestId('turnstile'))
    expect(screen.getByRole('button', { name: en.signup.common.submit })).toBeEnabled()
  })

  it('submits the token with the teacher payload', async () => {
    const user = userEvent.setup()
    renderForm('teacher')
    await fillAndSubmit(user)

    expect(registerAccount).toHaveBeenCalledTimes(1)
    expect(registerAccount.mock.calls[0]?.[0]).toMatchObject({
      role: 'teacher',
      full_name: 'Ayesha Teacher',
      turnstile_token: 'mock-token',
    })
    expect(push).toHaveBeenCalledWith('/onboarding/email')
  })

  it('clears the consumed token on CAPTCHA_FAILED and re-arms only after a fresh solve', async () => {
    registerAccount.mockRejectedValue(new ApiError(400, 'CAPTCHA_FAILED', 'no'))
    const user = userEvent.setup()
    renderForm('parent')
    await fillAndSubmit(user)

    expect(screen.getByRole('alert')).toHaveTextContent(en.signup.errors.captchaFailed)

    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))
    expect(registerAccount).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('turnstile'))
    await user.click(screen.getByRole('button', { name: en.signup.common.submit }))
    expect(registerAccount).toHaveBeenCalledTimes(2)
  })

  it('will not submit until passwords match', async () => {
    const user = userEvent.setup()
    renderForm('teacher')

    const submit = screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })
    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    await user.click(screen.getByTestId('turnstile'))
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
    await user.click(screen.getByTestId('turnstile'))

    expect(screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })).toBeEnabled()
  })
})