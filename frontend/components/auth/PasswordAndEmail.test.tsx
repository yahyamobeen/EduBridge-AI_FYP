import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import { __resetChallengesForTests, setUnverifiedEmail } from '@/lib/auth/challenge'
import { ForgotPassword } from './ForgotPassword'
import { ResetPassword } from './ResetPassword'
import { VerifyEmail } from './VerifyEmail'

const replace = vi.fn()
const push = vi.fn()
const forgot = vi.fn()
const reset = vi.fn()
const verify = vi.fn()
const resend = vi.fn()
const startSession = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push }),
  usePathname: () => '/verify-email',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({
  forgotPassword: (...a: unknown[]) => forgot(...a),
  resetPassword: (...a: unknown[]) => reset(...a),
  verifyEmail: (...a: unknown[]) => verify(...a),
  resendVerification: (...a: unknown[]) => resend(...a),
  startSession: (...a: unknown[]) => startSession(...a),
}))

const wrap = (ui: React.ReactNode) =>
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>,
  )

beforeEach(() => {
  replace.mockReset()
  push.mockReset()
  forgot.mockReset()
  reset.mockReset()
  verify.mockReset()
  resend.mockReset()
  startSession.mockReset()
  __resetChallengesForTests()
})

/**
 * The security property of this screen: the response is the same whether or not
 * the address exists, so the UI must be too. Anything else is an account
 * enumeration oracle anyone can query without signing in.
 */
describe('forgot password', () => {
  it('confirms identically for a known and an unknown address', async () => {
    const user = userEvent.setup()
    forgot.mockResolvedValue(undefined)
    wrap(<ForgotPassword />)

    await user.type(
      screen.getByLabelText(en.auth.forgotPassword.emailLabel),
      'nobody@example.com',
    )
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.forgotPassword.submit, 'i') }),
    )

    expect(screen.getByText(en.auth.forgotPassword.sentTitle)).toBeInTheDocument()
    // The copy is conditional on nothing the server said.
    expect(screen.getByText(/nobody@example\.com/)).toBeInTheDocument()
  })

  it('still surfaces rate limiting, which leaks nothing about the address', async () => {
    const user = userEvent.setup()
    forgot.mockRejectedValue(new ApiError(429, 'RATE_LIMITED', 'slow', { retry_after: 30 }))
    wrap(<ForgotPassword />)

    await user.type(screen.getByLabelText(en.auth.forgotPassword.emailLabel), 'a@example.com')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.forgotPassword.submit, 'i') }),
    )

    expect(screen.getByRole('alert')).toHaveTextContent(en.auth.errors.rateLimited)
  })
})

describe('reset password', () => {
  it('will not submit until the passwords match', async () => {
    const user = userEvent.setup()
    wrap(<ResetPassword token="reset-1" />)

    const submit = screen.getByRole('button', {
      name: new RegExp(en.auth.resetPassword.submit, 'i'),
    })
    await user.type(screen.getByLabelText(en.auth.resetPassword.newPassword), 'Password123')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(en.auth.resetPassword.confirmPassword), 'Password124')
    expect(screen.getByText(en.auth.resetPassword.mismatch)).toBeInTheDocument()
    expect(submit).toBeDisabled()

    await user.clear(screen.getByLabelText(en.auth.resetPassword.confirmPassword))
    await user.type(screen.getByLabelText(en.auth.resetPassword.confirmPassword), 'Password123')
    expect(submit).toBeEnabled()
  })

  it('gates only on length, leaving the real policy to the server', async () => {
    // Assumption A6: no source states the password policy, so the client must
    // not be stricter than the server it cannot see.
    const user = userEvent.setup()
    wrap(<ResetPassword token="reset-1" />)

    await user.type(screen.getByLabelText(en.auth.resetPassword.newPassword), 'alllowercase')
    await user.type(
      screen.getByLabelText(en.auth.resetPassword.confirmPassword),
      'alllowercase',
    )

    expect(
      screen.getByRole('button', { name: new RegExp(en.auth.resetPassword.submit, 'i') }),
    ).toBeEnabled()
  })

  it('shows the expired panel for an expired token, not a generic failure', async () => {
    const user = userEvent.setup()
    reset.mockRejectedValue(new ApiError(410, 'TOKEN_EXPIRED', 'gone'))
    wrap(<ResetPassword token="reset-1" />)

    await user.type(screen.getByLabelText(en.auth.resetPassword.newPassword), 'Password123')
    await user.type(screen.getByLabelText(en.auth.resetPassword.confirmPassword), 'Password123')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.resetPassword.submit, 'i') }),
    )

    expect(screen.getByText(en.auth.resetPassword.expiredTitle)).toBeInTheDocument()
  })

  it('treats a missing token as an invalid link before any request', () => {
    wrap(<ResetPassword token={null} />)
    expect(screen.getByText(en.auth.resetPassword.invalidTitle)).toBeInTheDocument()
    expect(reset).not.toHaveBeenCalled()
  })
})

describe('verify email', () => {
  it('exchanges the token once, even though React mounts effects twice in dev', async () => {
    verify.mockResolvedValue({
      email_verified: true,
      onboarding_state: 'two_factor_enrollment_pending',
      access_token: 'access-1',
      expires_in: 900,
      enrollment_token: 'enroll-1',
    })
    wrap(<VerifyEmail token="verify-u-s9" />)

    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.verifiedTitle)).toBeVisible(),
    )
    // A mail client prefetch plus the human click is already two requests; the
    // component must not add a third of its own.
    expect(verify).toHaveBeenCalledTimes(1)
    expect(startSession).toHaveBeenCalledWith('access-1', 900)
  })

  it('routes onward to enrolment, carrying the enrollment token', async () => {
    const user = userEvent.setup()
    verify.mockResolvedValue({
      email_verified: true,
      onboarding_state: 'two_factor_enrollment_pending',
      access_token: 'access-1',
      expires_in: 900,
      enrollment_token: 'enroll-1',
    })
    wrap(<VerifyEmail token="verify-u-s9" />)

    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.verifiedTitle)).toBeVisible(),
    )
    await user.click(screen.getByRole('button', { name: en.auth.verifyEmail.continue }))
    expect(replace).toHaveBeenCalledWith('/onboarding/2fa')
  })

  it('separates an expired link from a malformed one', async () => {
    verify.mockRejectedValue(new ApiError(410, 'TOKEN_EXPIRED', 'gone'))
    wrap(<VerifyEmail token="expired-token" />)
    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.expiredTitle)).toBeVisible(),
    )
  })

  it('falls back to the invalid panel for any other failure', async () => {
    verify.mockRejectedValue(new ApiError(400, 'INVALID_TOKEN', 'bad'))
    wrap(<VerifyEmail token="nonsense" />)
    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.invalidTitle)).toBeVisible(),
    )
  })

  it('resends to the address the user typed, not to a masked one', async () => {
    const user = userEvent.setup()
    setUnverifiedEmail('aisha@example.com')
    verify.mockRejectedValue(new ApiError(410, 'TOKEN_EXPIRED', 'gone'))
    resend.mockResolvedValue(undefined)
    wrap(<VerifyEmail token="expired-token" />)

    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.expiredTitle)).toBeVisible(),
    )
    await user.click(screen.getByRole('button', { name: en.auth.verifyEmail.resend }))

    expect(resend).toHaveBeenCalledWith({ email: 'aisha@example.com' })
  })

  it('sends the user to sign in when no address is known to resend to', async () => {
    const user = userEvent.setup()
    verify.mockRejectedValue(new ApiError(410, 'TOKEN_EXPIRED', 'gone'))
    wrap(<VerifyEmail token="expired-token" />)

    await waitFor(() =>
      expect(screen.getByText(en.auth.verifyEmail.expiredTitle)).toBeVisible(),
    )
    await user.click(screen.getByRole('button', { name: en.auth.verifyEmail.resend }))

    expect(resend).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith('/login')
  })
})
