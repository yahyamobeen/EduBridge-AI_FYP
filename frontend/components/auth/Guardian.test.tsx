import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import { GuardianConfirm } from './GuardianConfirm'
import { GuardianGate } from './GuardianGate'

const replace = vi.fn()
const invite = vi.fn()
const status = vi.fn()
const confirmLink = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => '/onboarding/guardian',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({
  guardianInvite: (...a: unknown[]) => invite(...a),
  guardianStatus: (...a: unknown[]) => status(...a),
  guardianConfirm: (...a: unknown[]) => confirmLink(...a),
}))

const wrap = (ui: React.ReactNode) =>
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>,
  )

beforeEach(() => {
  replace.mockReset()
  invite.mockReset()
  status.mockReset()
  confirmLink.mockReset()
})

describe('the student gate', () => {
  it('asks for the parent’s EMAIL, not for a code the student could forge', async () => {
    // Decision 1: a code the student types has passed through the student, so
    // it is not out-of-band. The prototype’s code field is deliberately gone.
    status.mockResolvedValue({
      required: true,
      status: null,
      parent_email: null,
      invited_at: null,
    })
    wrap(<GuardianGate />)

    await waitFor(() =>
      expect(screen.getByLabelText(en.auth.guardian.parentEmailLabel)).toBeVisible(),
    )
    expect(screen.queryByLabelText(/space code/i)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/G-/)).not.toBeInTheDocument()
  })

  it('moves to the waiting state after the invitation is sent', async () => {
    const user = userEvent.setup()
    status.mockResolvedValue({
      required: true,
      status: null,
      parent_email: null,
      invited_at: null,
    })
    invite.mockResolvedValue({
      invite_sent: true,
      parent_email: 'p***@example.com',
      status: 'pending',
    })
    wrap(<GuardianGate />)

    await waitFor(() =>
      expect(screen.getByLabelText(en.auth.guardian.parentEmailLabel)).toBeVisible(),
    )
    await user.type(
      screen.getByLabelText(en.auth.guardian.parentEmailLabel),
      'parent@example.com',
    )
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.guardian.sendInvite, 'i') }),
    )

    expect(invite).toHaveBeenCalledWith({ parent_email: 'parent@example.com' })
    expect(screen.getByText(en.auth.guardian.waiting)).toBeInTheDocument()
  })

  it('rejects the student inviting themselves, inline on the field', async () => {
    const user = userEvent.setup()
    status.mockResolvedValue({
      required: true,
      status: null,
      parent_email: null,
      invited_at: null,
    })
    invite.mockRejectedValue(new ApiError(422, 'SELF_LINK_FORBIDDEN', 'no'))
    wrap(<GuardianGate />)

    await waitFor(() =>
      expect(screen.getByLabelText(en.auth.guardian.parentEmailLabel)).toBeVisible(),
    )
    await user.type(screen.getByLabelText(en.auth.guardian.parentEmailLabel), 'me@example.com')
    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.guardian.sendInvite, 'i') }),
    )

    expect(screen.getByText(en.auth.guardian.selfLinkError)).toBeInTheDocument()
  })

  it('shows the verified state when the parent has already approved', async () => {
    status.mockResolvedValue({
      required: true,
      status: 'verified',
      parent_email: 'p***@example.com',
      invited_at: '2026-08-02T00:00:00Z',
    })
    wrap(<GuardianGate />)

    await waitFor(() => expect(screen.getByText(en.auth.guardian.verifiedTitle)).toBeVisible())
    expect(screen.queryByLabelText(en.auth.guardian.parentEmailLabel)).not.toBeInTheDocument()
  })
})

describe('the parent confirmation', () => {
  it('offers sign-up rather than a confirm button when there is no parent session', () => {
    // guardian/confirm is authenticated as the parent (decision 5), so the
    // client cannot confirm on their behalf.
    wrap(<GuardianConfirm token="invite-u-s9" signedIn={false} />)

    expect(screen.getByText(en.auth.guardianConfirm.signInFirst)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: new RegExp(en.auth.guardianConfirm.confirm, 'i') }),
    ).toBeDisabled()
  })

  it('states plainly that tutoring conversations stay private', () => {
    // prd.md §4.2 forbids a parent reading chat content. A parent authorising
    // access deserves to be told the boundary before they agree to it.
    wrap(<GuardianConfirm token="invite-u-s9" signedIn />)
    expect(screen.getByText(en.auth.guardianConfirm.step3)).toBeInTheDocument()
  })

  it('confirms the link and names the student', async () => {
    const user = userEvent.setup()
    confirmLink.mockResolvedValue({ status: 'verified', student_name: 'Aisha Khan' })
    wrap(<GuardianConfirm token="invite-u-s9" signedIn />)

    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.guardianConfirm.confirm, 'i') }),
    )

    expect(confirmLink).toHaveBeenCalledWith({ invite_token: 'invite-u-s9' })
    expect(screen.getByText(en.auth.guardianConfirm.confirmedTitle)).toBeInTheDocument()
    expect(screen.getByText(/Aisha Khan/)).toBeInTheDocument()
  })

  it('treats an already-linked account as done, not as an error', async () => {
    const user = userEvent.setup()
    confirmLink.mockRejectedValue(new ApiError(409, 'GUARDIAN_ALREADY_LINKED', 'linked'))
    wrap(<GuardianConfirm token="invite-u-s9" signedIn />)

    await user.click(
      screen.getByRole('button', { name: new RegExp(en.auth.guardianConfirm.confirm, 'i') }),
    )
    expect(screen.getByText(en.auth.guardianConfirm.alreadyTitle)).toBeInTheDocument()
  })

  it('shows the invalid panel without a request when the link carries no token', () => {
    wrap(<GuardianConfirm token={null} signedIn />)
    expect(screen.getByText(en.auth.guardianConfirm.invalidTitle)).toBeInTheDocument()
    expect(confirmLink).not.toHaveBeenCalled()
  })
})
