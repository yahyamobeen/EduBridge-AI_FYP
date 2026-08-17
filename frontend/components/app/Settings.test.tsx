import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Settings } from '@/components/app/Settings'
import en from '@/messages/en.json'
import type { MeResponse } from '@/lib/api/types'

/**
 * The settings screen — FR-A8's client.
 *
 * These cover the places where being wrong would be SILENT: a curriculum field
 * that looks editable, a language control that changes the page but not the
 * stored preference (or the reverse), and a board list taken from the prototype
 * rather than from the API.
 */

const replace = vi.fn()
vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => '/settings',
  Link: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const updateMe = vi.fn()
const changePassword = vi.fn()
const twoFactorStatus = vi.fn()
const getEnums = vi.fn()
const logout = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  updateMe: (...a: unknown[]) => updateMe(...a),
  changePassword: (...a: unknown[]) => changePassword(...a),
  twoFactorStatus: () => twoFactorStatus(),
  getEnums: () => getEnums(),
  logout: () => logout(),
  getMe: () => Promise.resolve(me),
}))

let me: MeResponse

function baseMe(overrides: Partial<MeResponse> = {}): MeResponse {
  return {
    user_id: 'u-1',
    email: 'aisha@example.com',
    full_name: 'Aisha Khan',
    language_pref: 'en',
    role: 'student',
    onboarding_state: 'active',
    email_verified: true,
    two_factor: { enabled: true, method: 'totp' },
    profile: {
      board: 'PCTB',
      class_level: 9,
      student_group: 'science',
      medium: 'en',
      language_pref: 'en',
    },
    guardian: { required: true, status: 'verified' },
    ...overrides,
  }
}

function renderSettings() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <Settings />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  me = baseMe()
  updateMe.mockResolvedValue(me)
  twoFactorStatus.mockResolvedValue({
    enabled: true,
    method: 'totp',
    locked_until: null,
    backup_codes_remaining: 7,
  })
  getEnums.mockResolvedValue({
    boards: [
      { code: 'PCTB', name: 'Punjab Curriculum and Textbook Board' },
      { code: 'STBB', name: 'Sindh Textbook Board' },
    ],
    class_levels: [9, 10, 11, 12],
    groups_by_class: {},
    mediums: ['en', 'ur'],
    languages: ['en', 'ur', 'roman_ur'],
  })
})

describe('curriculum context', () => {
  it('renders board and class as text, never as inputs', async () => {
    renderSettings()
    await screen.findByText(en.settings.profile.heading)

    // ⚠️ THE ASSERTION THAT MATTERS. The prototype draws these as editable
    // dropdowns; Phase 2 made both unwritable at the database (finding B4),
    // because `class_level` is the parental-consent gate input. A control the
    // user can change and the API silently refuses is worse than no control.
    for (const label of [en.settings.profile.board, en.settings.profile.classLevel]) {
      const field = screen.getByText(label)
      expect(field.tagName.toLowerCase()).toBe('label')
    }
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByLabelText(en.settings.profile.board)).not.toBeInTheDocument()
  })

  it('takes the board label from the API, not from a literal list', async () => {
    renderSettings()

    // The prototype offers FBISE / Punjab / Sindh / Cambridge. The enum is
    // PCTB and STBB, and the human-readable name is the API's to give.
    await screen.findByText('Punjab Curriculum and Textbook Board')
    expect(screen.queryByText('FBISE')).not.toBeInTheDocument()
    expect(screen.queryByText('Cambridge')).not.toBeInTheDocument()
  })

  it('omits the curriculum block entirely for a role that has no profile', async () => {
    me = baseMe({ role: 'teacher', profile: null, guardian: { required: false, status: null } })
    renderSettings()
    await screen.findByText(en.settings.profile.heading)

    expect(screen.queryByText(en.settings.profile.board)).not.toBeInTheDocument()
    // ...but the name field is still there: FR-A8 is "Role: all".
    expect(screen.getByLabelText(en.settings.profile.fullName)).toBeInTheDocument()
  })
})

describe('the language control does both things', () => {
  it('writes the stored preference AND changes the locale route', async () => {
    const user = userEvent.setup()
    renderSettings()
    await screen.findByText(en.settings.language.heading)

    await user.click(screen.getByLabelText(en.settings.language.option_ur))

    // ⚠️ BOTH, AND IN THIS ORDER. The stored preference governs outgoing email
    // and is an API write; the interface locale is a URL segment and is a route
    // change. Doing only the first leaves the page in the old language; doing
    // only the second leaves the server thinking nothing changed.
    await waitFor(() => expect(updateMe).toHaveBeenCalledWith({ language_pref: 'ur' }))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/settings', { locale: 'ur' }))
  })

  it('maps ur-Latn to roman_ur rather than passing the locale straight through', async () => {
    const user = userEvent.setup()
    renderSettings()
    await screen.findByText(en.settings.language.heading)

    await user.click(screen.getByLabelText(en.settings.language['option_ur-Latn']))

    // The two value sets are NOT the same strings. Sending `ur-Latn` would be a
    // 400 the user cannot act on.
    await waitFor(() => expect(updateMe).toHaveBeenCalledWith({ language_pref: 'roman_ur' }))
  })

  it('does not navigate when the write fails', async () => {
    const user = userEvent.setup()
    updateMe.mockRejectedValueOnce(new Error('network'))
    renderSettings()
    await screen.findByText(en.settings.language.heading)

    await user.click(screen.getByLabelText(en.settings.language.option_ur))

    await screen.findByText(en.settings.language.saveFailed)
    expect(replace).not.toHaveBeenCalled()
  })
})

describe('security', () => {
  it('shows the remaining backup code count without regenerating anything', async () => {
    renderSettings()

    // user-stories.md:93 — visible WITHOUT regenerating. Reading it must not
    // call an endpoint that replaces the codes, and no such endpoint exists.
    await screen.findByText('7')
    expect(twoFactorStatus).toHaveBeenCalledTimes(1)
  })

  it('reports a wrong current password from the code, not the message', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('@/lib/api/errors')
    changePassword.mockRejectedValueOnce(
      new ApiError(401, 'UNAUTHENTICATED', 'Incorrect password.', {}),
    )
    renderSettings()
    await screen.findByText(en.settings.security.heading)

    await user.type(screen.getByLabelText(en.settings.security.currentPassword), 'wrong-one')
    await user.type(screen.getByLabelText(en.settings.security.newPassword), 'Password123')
    await user.type(screen.getByLabelText(en.settings.security.confirmPassword), 'Password123')
    await user.click(screen.getByRole('button', { name: en.settings.security.changePassword }))

    await screen.findByText(en.settings.security.wrongPassword)
  })

  it('warns that changing the password signs the user out everywhere', async () => {
    renderSettings()
    // Not decoration: every refresh token is revoked including this session's,
    // so the next refresh failing is by design rather than a bug to report.
    await screen.findByText(en.settings.security.signsYouOut)
  })
})

describe('parental link', () => {
  it('is read-only and shown only when a gate applies', async () => {
    renderSettings()
    await screen.findByText(en.settings.guardian.heading)
    expect(screen.getByText(en.settings.guardian.status_verified)).toBeInTheDocument()
    expect(screen.getByText(en.settings.guardian.readOnly)).toBeInTheDocument()
  })

  it('is absent for a user with no gate', async () => {
    me = baseMe({ guardian: { required: false, status: null } })
    renderSettings()
    await screen.findByText(en.settings.profile.heading)
    expect(screen.queryByText(en.settings.guardian.heading)).not.toBeInTheDocument()
  })
})
