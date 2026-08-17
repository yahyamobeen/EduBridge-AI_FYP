import { render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import type { MeResponse, OnboardingState, Role } from '@/lib/api/types'
import { SessionGuard } from './SessionGuard'

const replace = vi.fn()
const me = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => '/dashboard',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({ getMe: () => me() }))

function identity(role: Role, state: OnboardingState): MeResponse {
  return {
    user_id: 'u-1',
    email: 'a@example.com',
    full_name: 'Aisha Khan',
    language_pref: 'en',
    role,
    onboarding_state: state,
    email_verified: true,
    two_factor: { enabled: true, method: 'totp' },
    profile: null,
    guardian: { required: false, status: null },
  }
}

function renderGuard(allow: Role[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SessionGuard allow={allow}>{(user) => <p>welcome {user.full_name}</p>}</SessionGuard>
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  replace.mockReset()
  me.mockReset()
})

describe('the three checks, in order', () => {
  it('sends a signed-out visitor to sign in', async () => {
    me.mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'no'))
    renderGuard(['student'])
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'))
  })

  it('sends an incomplete journey to the step that completes it', async () => {
    me.mockResolvedValue(identity('student', 'guardian_link_pending'))
    renderGuard(['student'])
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/guardian'))
  })

  it('sends the wrong role to its own dashboard, not to an error', async () => {
    me.mockResolvedValue(identity('parent', 'active'))
    renderGuard(['student'])
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/parent'))
  })

  it('renders the page for the right role on a complete journey', async () => {
    me.mockResolvedValue(identity('student', 'active'))
    renderGuard(['student'])
    await waitFor(() => expect(screen.getByText(/welcome Aisha Khan/)).toBeVisible())
    expect(replace).not.toHaveBeenCalled()
  })
})

/**
 * Onboarding is not monotonic (prd.md §2.6 MON-4). A student who was `active`
 * returns to `plan_selection_pending` when the trial lapses, so the state has
 * to be re-read rather than remembered — the "check once, then trust" guard
 * that most people write would strand them on a page they no longer have
 * rights to.
 */
describe('the non-monotonic case', () => {
  it('redirects a formerly active student whose trial has lapsed', async () => {
    me.mockResolvedValue(identity('student', 'plan_selection_pending'))
    renderGuard(['student'])
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/plan'))
    expect(screen.queryByText(/welcome/)).not.toBeInTheDocument()
  })

  it('re-reads identity on every mount instead of trusting a previous pass', async () => {
    me.mockResolvedValue(identity('student', 'active'))
    const first = renderGuard(['student'])
    await waitFor(() => expect(screen.getByText(/welcome/)).toBeVisible())
    first.unmount()

    // The trial lapses between visits.
    me.mockResolvedValue(identity('student', 'plan_selection_pending'))
    renderGuard(['student'])
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/plan'))
    expect(me).toHaveBeenCalledTimes(2)
  })
})

describe('while deciding', () => {
  it('renders no page content, so nothing flashes before a redirect', () => {
    me.mockReturnValue(new Promise(() => {}))
    renderGuard(['student'])
    expect(screen.queryByText(/welcome/)).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(en.app.loading)
  })
})
