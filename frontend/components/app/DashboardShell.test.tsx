import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import type { MeResponse } from '@/lib/api/types'
import { DashboardShell } from './DashboardShell'

/**
 * Finding A8: sign-out silently did nothing when the network failed.
 *
 * `logout()` clears the in-memory session in a `finally` and then RE-THROWS,
 * deliberately — dropping the local session matters more than the server call
 * succeeding. `signOut` awaited it with no `catch`, so on a failure the throw
 * escaped, `router.replace` never ran, and the dashboard stayed on screen fully
 * rendered: `me` is already in state and `SessionGuard` has already passed.
 *
 * The user clicked "sign out" and nothing changed. On the shared devices
 * prd.md §3.1 describes, they walk away from a page still showing their name.
 */

const replace = vi.fn()
const logout = vi.fn()
let pathname = '/dashboard'

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => pathname,
  // Passes every prop through: `aria-current` is what the sidebar tests read.
  Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props}>{children}</a>
  ),
}))
vi.mock('@/lib/api/endpoints', () => ({ logout: () => logout() }))

const me: MeResponse = {
  user_id: 'u-1',
  email: 'aisha@example.com',
  full_name: 'Aisha Khan',
  language_pref: 'en',
  role: 'student',
  onboarding_state: 'active',
  email_verified: true,
  two_factor: { enabled: true, method: 'totp' },
  profile: null,
  guardian: { required: false, status: null },
}

function shell(user: MeResponse = me) {
  return (
    <NextIntlClientProvider locale="en" messages={en}>
      <DashboardShell me={user} subtitle="Student Dashboard">
        <p>dashboard content</p>
      </DashboardShell>
    </NextIntlClientProvider>
  )
}

function renderShell(user: MeResponse = me) {
  return render(shell(user))
}

function clickSignOut() {
  // There is a docked sidebar and a mobile disclosure, so the control can be
  // rendered more than once; the first is the docked one.
  fireEvent.click(screen.getAllByRole('button', { name: en.nav.items.logout })[0]!)
}

beforeEach(() => {
  replace.mockReset()
  logout.mockReset()
  pathname = '/dashboard'
})

describe('signing out', () => {
  it('redirects to sign-in on success', async () => {
    logout.mockResolvedValue(undefined)
    renderShell()
    clickSignOut()

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'))
  })

  it('STILL redirects when the server call fails', async () => {
    // The regression this file exists for. `logout()` has already cleared the
    // token by the time it rejects, so staying put leaves a signed-out user
    // looking at a signed-in page.
    logout.mockRejectedValue(new Error('network down'))
    renderShell()
    clickSignOut()

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/login'))
  })

  it('calls logout exactly once per click', async () => {
    logout.mockResolvedValue(undefined)
    renderShell()
    clickSignOut()

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1))
  })
})

describe('the sidebar', () => {
  it('renders the items for the role, not a hardcoded list', () => {
    logout.mockResolvedValue(undefined)
    renderShell()

    // A parent once ended up with an AI-tutor replay button because the three
    // dashboard mockups shipped one identical sidebar; the list comes from
    // NAV_BY_ROLE precisely so that cannot recur.
    expect(screen.getAllByText(en.nav.items.myClasses).length).toBeGreaterThan(0)
    expect(screen.queryByText(en.nav.items.myChild)).not.toBeInTheDocument()
  })
})

/**
 * The item for the page you are on is the one marked current. It used to be
 * the FIRST item on every page — so a student inside a classroom saw
 * "Dashboard" highlighted (owner report, 2026-10-05). The longest matching
 * prefix wins, so a teacher's classroom is not their dashboard at /teacher.
 */
describe('the current page', () => {
  function current() {
    const nav = screen.getByRole('navigation', { name: en.dashboard.primaryNav })
    return within(nav)
      .queryAllByRole('link')
      .filter((a) => a.getAttribute('aria-current') === 'page')
      .map((a) => a.textContent)
  }

  it.each([
    ['/dashboard', en.nav.items.dashboard],
    ['/classroom', en.nav.items.myClasses],
    ['/classroom/11111111-1111-4111-8111-111111111111', en.nav.items.myClasses],
    ['/classroom/calendar', en.nav.items.myClasses],
    ['/settings', en.nav.items.settings],
  ])('on %s it is %s, and only that', (path, label) => {
    pathname = path
    renderShell()
    expect(current()).toEqual([label])
  })

  it("a teacher's classroom is not their dashboard, though /teacher is its prefix", () => {
    pathname = '/teacher/classroom/calendar'
    renderShell({ ...me, role: 'teacher' })
    expect(current()).toEqual([en.nav.items.mySpaces])
  })

  it('marks nothing on a path no item owns, rather than guessing', () => {
    pathname = '/somewhere-else'
    renderShell()
    expect(current()).toEqual([])
  })
})

/**
 * Since Phase 6c the shell lives in the (app) layout and a navigation no longer
 * remounts it — which used to be the only thing that closed the phone menu.
 */
describe('the phone menu', () => {
  it('closes when the page changes', () => {
    const view = renderShell()
    fireEvent.click(screen.getByRole('button', { name: en.dashboard.openMenu }))
    expect(document.getElementById('mobile-nav')).not.toBeNull()
    pathname = '/classroom'
    view.rerender(shell())
    expect(document.getElementById('mobile-nav')).toBeNull()
  })
})
