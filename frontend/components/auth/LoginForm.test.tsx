import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import {
  __resetChallengesForTests,
  getEnrollmentHandoff,
  getPendingChallenge,
  getUnverifiedEmail,
} from '@/lib/auth/challenge'
import { LoginForm } from './LoginForm'

const push = vi.fn()
const signIn = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push }),
  // The screen renders no top nav, so it carries its own language switcher —
  // which needs the locale-aware pathname.
  usePathname: () => '/login',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({ login: (...a: unknown[]) => signIn(...a) }))

function renderForm() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <LoginForm />
    </NextIntlClientProvider>,
  )
}

async function signInAs(user: ReturnType<typeof userEvent.setup>, email = 'aisha@example.com') {
  await user.type(screen.getByLabelText(en.auth.login.emailLabel), email)
  await user.type(screen.getByLabelText(en.auth.login.passwordLabel), 'Password123')
  await user.click(screen.getByRole('button', { name: new RegExp(en.auth.login.submit, 'i') }))
}

beforeEach(() => {
  push.mockReset()
  signIn.mockReset()
  __resetChallengesForTests()
})

/**
 * The branch that matters most: a 200 is never an error. Each status has to
 * move the user forward, and each has to leave behind the credential the next
 * screen needs.
 */
describe('a 200 always advances', () => {
  it('sends an enrolled user to the challenge with the server-chosen method', async () => {
    signIn.mockResolvedValue({
      status: 'two_factor_required',
      pending_token: 'pending-1',
      method: 'email_otp',
      expires_in: 300,
    })
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(push).toHaveBeenCalledWith('/login/2fa')
    const challenge = getPendingChallenge()
    expect(challenge?.token).toBe('pending-1')
    // Not defaulted to TOTP: a student enrolled in email OTP must land on the
    // screen for the factor they actually have.
    expect(challenge?.method).toBe('email_otp')
  })

  it('sends an un-enrolled user to enrolment with the enrollment token', async () => {
    signIn.mockResolvedValue({
      status: 'two_factor_enrollment_required',
      enrollment_token: 'enroll-1',
      expires_in: 600,
    })
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(push).toHaveBeenCalledWith('/onboarding/2fa')
    expect(getEnrollmentHandoff()?.token).toBe('enroll-1')
  })

  it('keeps the UNMASKED address when the email is unverified', async () => {
    // The response carries a masked address, which /auth/email/resend cannot
    // act on. What the user typed is the only usable value.
    signIn.mockResolvedValue({
      status: 'email_verification_required',
      email: 'a***@example.com',
    })
    const user = userEvent.setup()
    renderForm()
    await signInAs(user, 'aisha@example.com')

    expect(push).toHaveBeenCalledWith('/onboarding/email')
    expect(getUnverifiedEmail()).toBe('aisha@example.com')
  })

  it('shows no error banner on any successful status', async () => {
    signIn.mockResolvedValue({
      status: 'email_verification_required',
      email: 'a***@example.com',
    })
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('failures', () => {
  it('shows one neutral message for a 401, revealing nothing about the account', async () => {
    signIn.mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'nope'))
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(screen.getByRole('alert')).toHaveTextContent(en.auth.errors.badCredentials)
    expect(push).not.toHaveBeenCalled()
  })

  it('replaces the form with the locked panel on a 423', async () => {
    signIn.mockRejectedValue(
      new ApiError(423, 'TWO_FACTOR_LOCKED', 'locked', {
        locked_until: new Date(Date.now() + 900_000).toISOString(),
      }),
    )
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(screen.getByText(en.auth.locked.title)).toBeInTheDocument()
    expect(screen.queryByLabelText(en.auth.login.emailLabel)).not.toBeInTheDocument()
  })

  it('disables submission while rate limited', async () => {
    signIn.mockRejectedValue(
      new ApiError(429, 'RATE_LIMITED', 'slow down', { retry_after: 30 }),
    )
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    expect(screen.getByRole('alert')).toHaveTextContent(en.auth.errors.rateLimitedIn)
    expect(
      screen.getByRole('button', { name: new RegExp(en.auth.login.submit, 'i') }),
    ).toBeDisabled()
  })

  it('puts a VALIDATION_ERROR on the field it belongs to', async () => {
    signIn.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'bad', {
        fields: { email: 'Enter a valid email address.' },
      }),
    )
    const user = userEvent.setup()
    renderForm()
    await signInAs(user)

    const field = screen.getByLabelText(en.auth.login.emailLabel)
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid email address.')
  })
})

describe('what the prototype got wrong', () => {
  it('offers no social sign-in, which has no endpoint behind it', () => {
    renderForm()
    expect(screen.queryByRole('button', { name: /google/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /microsoft/i })).not.toBeInTheDocument()
  })

  it('sends new users to the role chooser, not straight to the student form', () => {
    renderForm()
    expect(screen.getByRole('link', { name: en.auth.login.createAccount })).toHaveAttribute(
      'href',
      '/signup',
    )
  })
})
