import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import urLatn from '@/messages/ur-Latn.json'
import ur from '@/messages/ur.json'
import { ApiError } from '@/lib/api/errors'
import type { TwoFactorMethod } from '@/lib/api/types'
import { __resetChallengesForTests, setPendingChallenge } from '@/lib/auth/challenge'
import { TwoFactorChallenge } from './TwoFactorChallenge'

const replace = vi.fn()
const verify = vi.fn()
const me = vi.fn()
const startSession = vi.fn()
const resend = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace }),
  usePathname: () => '/login/2fa',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({
  twoFactorVerify: (...a: unknown[]) => verify(...a),
  getMe: (...a: unknown[]) => me(...a),
  startSession: (...a: unknown[]) => startSession(...a),
  // `twoFactorResend` was MISSING from this mock, which is a symptom of the
  // gap the translations suite below closes: the resend control was never
  // rendered by any test, so nothing here could have touched it.
  twoFactorResend: (...a: unknown[]) => resend(...a),
}))

function seed(method: TwoFactorMethod = 'totp') {
  setPendingChallenge({
    token: 'pending-1',
    method,
    expiresAtMs: Date.now() + 300_000,
    email: 'aisha@example.com',
  })
}

function renderChallenge() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <TwoFactorChallenge />
    </NextIntlClientProvider>,
  )
}

const codeField = () => screen.getByLabelText(en.auth.twoFactor.codeLabel)
const verifyButton = () =>
  screen.getByRole('button', { name: new RegExp(en.auth.twoFactor.verify, 'i') })

beforeEach(() => {
  replace.mockReset()
  verify.mockReset()
  me.mockReset()
  startSession.mockReset()
  resend.mockReset()
  __resetChallengesForTests()
})

describe('translations', () => {
  /**
   * THE TEST THAT WAS MISSING, AND WHAT IT COST.
   *
   * `t('resend')`, `t('resending')` and `t('resent')` existed in the component
   * and in NONE of the three locale files. Measured before this suite was
   * added: the control rendered the literal string `auth.twoFactor.resend`.
   *
   * Nothing failed, for two compounding reasons. next-intl reports a missing
   * key through `onError` rather than throwing, so a missing string renders as
   * its own key path and the render "succeeds" — which is exactly why the house
   * pattern (`Landing.test.tsx`) asserts on `onError` and why this screen needed
   * the same. And the resend control only renders while `type === 'email_otp'`,
   * a branch no existing test reached, so the keys were never even looked up.
   *
   * ⚠️ For an `email_otp` account that button is currently the ONLY way to get a
   * code, because `login` does not send one — `_issue_and_send_email_otp` is
   * called from `two_factor_enroll` and `two_factor_resend` and nowhere else.
   * That defect is deferred to Phase 5; this suite makes sure the remedy at
   * least has a label. Until then `methodEmailBody` ("the code sent to …") is
   * inaccurate for a fresh challenge, and that is recorded rather than papered
   * over.
   */
  it.each([
    ['en', en],
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders the email-code challenge fully in %s', (locale, messages) => {
    seed('email_otp')
    const onError = vi.fn()

    render(
      <NextIntlClientProvider locale={locale} messages={messages} onError={onError}>
        <TwoFactorChallenge />
      </NextIntlClientProvider>,
    )

    expect(onError).not.toHaveBeenCalled()
    // Named explicitly, not just "no errors": a future edit that deletes the
    // control entirely would satisfy `onError` and lose the only way in.
    expect(
      screen.getByRole('button', { name: messages.auth.twoFactor.resend }),
    ).toBeInTheDocument()
  })

  it.each([
    ['en', en],
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders the authenticator challenge fully in %s', (locale, messages) => {
    seed('totp')
    const onError = vi.fn()

    render(
      <NextIntlClientProvider locale={locale} messages={messages} onError={onError}>
        <TwoFactorChallenge />
      </NextIntlClientProvider>,
    )

    expect(onError).not.toHaveBeenCalled()
  })
})

describe('opening state', () => {
  it('returns to sign-in when there is no challenge in memory', () => {
    renderChallenge()
    expect(replace).toHaveBeenCalledWith('/login')
    expect(screen.queryByText(en.auth.twoFactor.title)).not.toBeInTheDocument()
  })

  it('opens on the method the server chose, not on TOTP', () => {
    seed('email_otp')
    renderChallenge()
    // The masked address proves it is the email prompt, not the app prompt.
    expect(screen.getByText(/a\*+@example\.com/)).toBeInTheDocument()
    expect(screen.queryByText(en.auth.twoFactor.promptTotp)).not.toBeInTheDocument()
  })

  it('opens on the authenticator prompt when that is the enrolled method', () => {
    seed('totp')
    renderChallenge()
    expect(screen.getByText(en.auth.twoFactor.promptTotp)).toBeInTheDocument()
  })
})

describe('method switching', () => {
  it('changes the submitted type and the code length', async () => {
    seed('totp')
    verify.mockResolvedValue({
      access_token: 'access-1',
      token_type: 'bearer',
      expires_in: 900,
      onboarding_state: 'guardian_link_pending',
    })
    const user = userEvent.setup()
    renderChallenge()

    expect(codeField()).toHaveAttribute('maxlength', '6')

    await user.click(screen.getByRole('button', { name: en.auth.twoFactor.tryAnotherWay }))
    await user.click(screen.getByRole('button', { name: /backup code/i }))

    // 8 alphanumerics, case-insensitive (decision 9).
    expect(codeField()).toHaveAttribute('maxlength', '8')
    await user.type(codeField(), 'bkup0000')
    expect(codeField()).toHaveValue('BKUP0000')

    await user.click(verifyButton())
    expect(verify).toHaveBeenCalledWith({
      pending_token: 'pending-1',
      code: 'BKUP0000',
      type: 'backup_code',
    })
  })

  it('offers a way back to the enrolled method from the backup code', async () => {
    seed('totp')
    const user = userEvent.setup()
    renderChallenge()

    await user.click(screen.getByRole('button', { name: en.auth.twoFactor.tryAnotherWay }))
    await user.click(screen.getByRole('button', { name: /backup code/i }))
    await user.click(screen.getByRole('button', { name: en.auth.twoFactor.tryAnotherWay }))
    await user.click(screen.getByRole('button', { name: /authenticator app/i }))

    expect(codeField()).toHaveAttribute('maxlength', '6')
  })
})

describe('the code field', () => {
  it('keeps a leading zero, which type="number" would have eaten', async () => {
    seed('totp')
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '012345')
    expect(codeField()).toHaveValue('012345')
  })

  it('will not submit a partial code', async () => {
    seed('totp')
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '123')
    expect(verifyButton()).toBeDisabled()
  })
})

describe('outcomes', () => {
  it('stores the session and routes to the next onboarding step', async () => {
    seed('totp')
    verify.mockResolvedValue({
      access_token: 'access-1',
      token_type: 'bearer',
      expires_in: 900,
      onboarding_state: 'guardian_link_pending',
    })
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '123456')
    await user.click(verifyButton())

    expect(startSession).toHaveBeenCalledWith('access-1', 900)
    expect(replace).toHaveBeenCalledWith('/onboarding/guardian')
    // No identity call needed: the destination did not depend on the role.
    expect(me).not.toHaveBeenCalled()
  })

  it('asks for the role only when the user is fully onboarded', async () => {
    seed('totp')
    verify.mockResolvedValue({
      access_token: 'access-1',
      token_type: 'bearer',
      expires_in: 900,
      onboarding_state: 'active',
    })
    me.mockResolvedValue({ role: 'teacher' })
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '123456')
    await user.click(verifyButton())

    expect(me).toHaveBeenCalled()
    expect(replace).toHaveBeenCalledWith('/teacher')
  })

  it('clears and re-prompts on a rejected code', async () => {
    seed('totp')
    verify.mockRejectedValue(new ApiError(401, 'TWO_FACTOR_INVALID', 'nope'))
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '000000')
    await user.click(verifyButton())

    expect(screen.getByText(en.auth.errors.invalidCode)).toBeInTheDocument()
    expect(codeField()).toHaveValue('')
    expect(codeField()).toHaveAttribute('aria-invalid', 'true')
  })

  it('offers a restart when the challenge token has expired', async () => {
    seed('totp')
    verify.mockRejectedValue(new ApiError(401, 'PENDING_TOKEN_EXPIRED', 'gone'))
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '123456')
    await user.click(verifyButton())

    expect(screen.getByText(en.auth.twoFactor.expiredTitle)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: en.auth.twoFactor.backToSignIn }))
    expect(replace).toHaveBeenLastCalledWith('/login')
  })

  it('shows the locked panel on a 423 and hides the code field', async () => {
    seed('totp')
    verify.mockRejectedValue(
      new ApiError(423, 'TWO_FACTOR_LOCKED', 'locked', {
        locked_until: new Date(Date.now() + 900_000).toISOString(),
      }),
    )
    const user = userEvent.setup()
    renderChallenge()

    await user.type(codeField(), '123456')
    await user.click(verifyButton())

    expect(screen.getByText(en.auth.locked.title)).toBeInTheDocument()
    expect(screen.queryByLabelText(en.auth.twoFactor.codeLabel)).not.toBeInTheDocument()
  })
})
