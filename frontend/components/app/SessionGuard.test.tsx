import { render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import type { MeResponse, OnboardingState, Role } from '@/lib/api/types'
import { RequireRole, SessionGuard } from './SessionGuard'

/**
 * The gate, since classroom Phase 6c split in two: `SessionGuard` sits in the
 * `(app)` layout and decides who is signed in and whether their journey is
 * complete; `RequireRole` sits in each page and decides whether this role may
 * see it. The page changes; the guard — and the sidebar it carries — stays.
 */

const replace = vi.fn()
const me = vi.fn()
let pathname = '/dashboard'

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => pathname,
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

function tree(allow: Role[]) {
  return (
    <NextIntlClientProvider locale="en" messages={en}>
      <SessionGuard>
        {() => (
          <RequireRole allow={allow}>{(user) => <p>welcome {user.full_name}</p>}</RequireRole>
        )}
      </SessionGuard>
    </NextIntlClientProvider>
  )
}

beforeEach(() => {
  replace.mockReset()
  me.mockReset()
  pathname = '/dashboard'
})

describe('the three checks, in order', () => {
  it('sends a signed-out visitor to sign in', async () => {
    me.mockRejectedValue(new ApiError(401, 'UNAUTHENTICATED', 'no'))
    render(tree(['student']))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'))
  })

  it('sends an incomplete journey to the step that completes it', async () => {
    me.mockResolvedValue(identity('student', 'guardian_link_pending'))
    render(tree(['student']))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/guardian'))
  })

  it('sends the wrong role to its own dashboard, not to an error', async () => {
    me.mockResolvedValue(identity('parent', 'active'))
    render(tree(['student']))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/parent'))
    expect(screen.queryByText(/welcome/)).not.toBeInTheDocument()
  })

  it('renders the page for the right role on a complete journey', async () => {
    me.mockResolvedValue(identity('student', 'active'))
    render(tree(['student']))
    await waitFor(() => expect(screen.getByText(/welcome Aisha Khan/)).toBeVisible())
    expect(replace).not.toHaveBeenCalled()
  })
})

/**
 * Onboarding is not monotonic (prd.md §2.6 MON-4). A student who was `active`
 * returns to `plan_selection_pending` when the trial lapses, so the state has
 * to be re-read rather than remembered — the "check once, then trust" guard
 * that most people write would strand them on a page they no longer have
 * rights to. Since Phase 6c the re-read happens on every NAVIGATION, in the
 * background, instead of on every mount behind a blank screen.
 */
describe('the non-monotonic case', () => {
  it('redirects a formerly active student whose trial has lapsed', async () => {
    me.mockResolvedValue(identity('student', 'plan_selection_pending'))
    render(tree(['student']))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/plan'))
    expect(screen.queryByText(/welcome/)).not.toBeInTheDocument()
  })

  it('re-reads identity on every navigation instead of trusting a previous pass', async () => {
    me.mockResolvedValue(identity('student', 'active'))
    const view = render(tree(['student']))
    await waitFor(() => expect(screen.getByText(/welcome/)).toBeVisible())

    // The trial lapses, and the student moves to another page.
    me.mockResolvedValue(identity('student', 'plan_selection_pending'))
    pathname = '/classroom'
    view.rerender(tree(['student']))
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding/plan'))
    expect(me).toHaveBeenCalledTimes(2)
  })

  it('keeps the page and the frame on screen while it re-checks', async () => {
    me.mockResolvedValue(identity('student', 'active'))
    const view = render(tree(['student']))
    const before = await screen.findByText(/welcome/)

    me.mockReturnValue(new Promise(() => {})) // a slow re-check
    pathname = '/classroom'
    view.rerender(tree(['student']))
    // No "Loading…" in its place, and the same node: nothing was unmounted.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText(/welcome/)).toBe(before)
    expect(me).toHaveBeenCalledTimes(2)
  })
})

describe('while deciding, on first entry', () => {
  it('renders no page content, so nothing flashes before a redirect', () => {
    me.mockReturnValue(new Promise(() => {}))
    render(tree(['student']))
    expect(screen.queryByText(/welcome/)).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(en.app.loading)
  })
})
