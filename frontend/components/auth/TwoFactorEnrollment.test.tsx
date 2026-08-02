import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import { __resetChallengesForTests, setEnrollmentHandoff } from '@/lib/auth/challenge'
import { TwoFactorEnrollment } from './TwoFactorEnrollment'

const replace = vi.fn()
const enroll = vi.fn()
const confirm = vi.fn()
const startSession = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => '/onboarding/2fa',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({
  twoFactorEnroll: (...a: unknown[]) => enroll(...a),
  twoFactorConfirm: (...a: unknown[]) => confirm(...a),
  startSession: (...a: unknown[]) => startSession(...a),
}))

const TOTP_RESPONSE = {
  method: 'totp',
  secret: 'JBSWY3DPEHPK3PXP',
  otpauth_uri: 'otpauth://totp/EduBridge:a@example.com?secret=JBSWY3DPEHPK3PXP',
  qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"></svg>',
}

function seed() {
  setEnrollmentHandoff({
    token: 'enroll-1',
    expiresAtMs: Date.now() + 600_000,
    email: 'aisha@example.com',
  })
}

function renderEnrollment() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <TwoFactorEnrollment />
    </NextIntlClientProvider>,
  )
}

const totpOption = () => screen.getByRole('button', { name: /authenticator app/i })
const emailOption = () => screen.getByRole('button', { name: /email code/i })

beforeEach(() => {
  replace.mockReset()
  enroll.mockReset()
  confirm.mockReset()
  startSession.mockReset()
  __resetChallengesForTests()
})

describe('entry', () => {
  it('returns to sign-in without an enrollment token', () => {
    renderEnrollment()
    expect(replace).toHaveBeenCalledWith('/login')
  })
})

/**
 * The review gate for this screen. Burying email OTP would lock out students
 * without a smartphone, which is the audience prd.md §3.1 and NFR-2 describe.
 */
describe('equal prominence of the two methods', () => {
  it('offers both, with neither preselected and neither hidden', () => {
    seed()
    renderEnrollment()

    expect(totpOption()).toBeVisible()
    expect(emailOption()).toBeVisible()
    // Nothing is chosen for the user: no code field exists until they pick.
    expect(screen.queryByLabelText(en.auth.enroll.codeLabel)).not.toBeInTheDocument()
  })

  it('renders both options through the same control, at the same weight', () => {
    seed()
    renderEnrollment()
    // Same element type and same class list means neither can be visually
    // demoted without demoting both.
    expect(totpOption().tagName).toBe(emailOption().tagName)
    expect(totpOption().className).toBe(emailOption().className)
  })
})

describe('TOTP setup', () => {
  it('renders the QR as an image source, never as injected markup', async () => {
    seed()
    enroll.mockResolvedValue(TOTP_RESPONSE)
    const user = userEvent.setup()
    renderEnrollment()
    await user.click(totpOption())

    const qr = screen.getByAltText(en.auth.enroll.qrAlt)
    // A data-URI <img> executes no scripts and makes no external request
    // (tdd.md §6.11). Injecting the same string as HTML would do both.
    expect(qr.getAttribute('src')).toMatch(/^data:image\/svg\+xml,/)
    expect(qr.tagName).toBe('IMG')
  })

  it('shows the secret for anyone who cannot scan', async () => {
    seed()
    enroll.mockResolvedValue(TOTP_RESPONSE)
    const user = userEvent.setup()
    renderEnrollment()
    await user.click(totpOption())

    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
  })

  it('sends the enrollment token in the body, not as a bearer', async () => {
    seed()
    enroll.mockResolvedValue(TOTP_RESPONSE)
    const user = userEvent.setup()
    renderEnrollment()
    await user.click(totpOption())

    expect(enroll).toHaveBeenCalledWith({ method: 'totp', enrollment_token: 'enroll-1' })
  })
})

describe('confirmation', () => {
  async function reachCodeEntry(user: ReturnType<typeof userEvent.setup>) {
    seed()
    enroll.mockResolvedValue(TOTP_RESPONSE)
    renderEnrollment()
    await user.click(totpOption())
  }

  it('stores the session and shows the backup codes', async () => {
    const user = userEvent.setup()
    await reachCodeEntry(user)

    confirm.mockResolvedValue({
      two_factor: { enabled: true, method: 'totp' },
      backup_codes: ['AAAA1111', 'BBBB2222'],
      onboarding_state: 'guardian_link_pending',
      access_token: 'access-1',
      expires_in: 900,
    })

    await user.type(screen.getByLabelText(en.auth.enroll.codeLabel), '123456')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.enroll.confirm, 'i') }),
    )

    expect(startSession).toHaveBeenCalledWith('access-1', 900)
    expect(screen.getByText('AAAA1111')).toBeInTheDocument()
    // Not routed yet: the codes have to be acknowledged first.
    expect(replace).not.toHaveBeenCalled()
  })

  it('clears and re-prompts on a rejected code', async () => {
    const user = userEvent.setup()
    await reachCodeEntry(user)
    confirm.mockRejectedValue(new ApiError(401, 'TWO_FACTOR_INVALID', 'nope'))

    await user.type(screen.getByLabelText(en.auth.enroll.codeLabel), '000000')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.enroll.confirm, 'i') }),
    )

    expect(screen.getByText(en.auth.errors.invalidCode)).toBeInTheDocument()
    expect(screen.getByLabelText(en.auth.enroll.codeLabel)).toHaveValue('')
  })
})

describe('backup codes', () => {
  async function reachCodes(user: ReturnType<typeof userEvent.setup>) {
    seed()
    enroll.mockResolvedValue(TOTP_RESPONSE)
    confirm.mockResolvedValue({
      two_factor: { enabled: true, method: 'totp' },
      backup_codes: ['AAAA1111', 'BBBB2222'],
      onboarding_state: 'guardian_link_pending',
      access_token: 'access-1',
      expires_in: 900,
    })
    renderEnrollment()
    await user.click(totpOption())
    await user.type(screen.getByLabelText(en.auth.enroll.codeLabel), '123456')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.enroll.confirm, 'i') }),
    )
  }

  it('gates continue behind the acknowledgement, not behind a warning', async () => {
    // beforeunload is unreliable on mobile Safari, so the checkbox is the real
    // safeguard against leaving without saving the codes.
    const user = userEvent.setup()
    await reachCodes(user)

    const cont = screen.getByRole('button', { name: en.auth.backupCodes.continue })
    expect(cont).toBeDisabled()

    await user.click(screen.getByRole('checkbox'))
    expect(cont).toBeEnabled()

    await user.click(cont)
    expect(replace).toHaveBeenCalledWith('/onboarding/guardian')
  })
})
