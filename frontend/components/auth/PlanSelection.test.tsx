import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { ApiError } from '@/lib/api/errors'
import { PlanSelection } from './PlanSelection'

const replace = vi.fn()
const apiFetch = vi.fn()

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => '/onboarding/plan',
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/api/client', () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

const wrap = () =>
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Karachi">
      <PlanSelection />
    </NextIntlClientProvider>,
  )

beforeEach(() => {
  replace.mockReset()
  apiFetch.mockReset()
})

describe('what the screen offers', () => {
  it('shows one tier at Rs. 999, superseding the prototype’s two', async () => {
    apiFetch.mockResolvedValue({
      plan: { code: 'standard', name: 'EduBridge AI', price_minor: 99900, currency: 'PKR' },
      status: 'trialing',
      trial_ends_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
      current_period_end: null,
    })
    wrap()

    await waitFor(() => expect(screen.getByText(en.plan.price)).toBeVisible())
    // prd.md §2.6: no free tier. The prototype's "Basic — Free" card would be a
    // promise the product does not keep.
    expect(screen.queryByText(/free tier|basic/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/1,500/)).not.toBeInTheDocument()
  })

  it('takes no payment details, because no provider is chosen yet', async () => {
    apiFetch.mockResolvedValue({
      plan: { code: 'standard', name: 'EduBridge AI', price_minor: 99900, currency: 'PKR' },
      status: 'trialing',
      trial_ends_at: null,
      current_period_end: null,
    })
    wrap()

    await waitFor(() => expect(screen.getByText(en.plan.statusTitle)).toBeVisible())
    expect(screen.queryByLabelText(/card number|cvv|expiry/i)).not.toBeInTheDocument()
    expect(screen.getByText(en.plan.noCheckoutNote)).toBeInTheDocument()
  })
})

describe('trial status', () => {
  it('reports the trial end from the server timestamp', async () => {
    apiFetch.mockResolvedValue({
      plan: { code: 'standard', name: 'EduBridge AI', price_minor: 99900, currency: 'PKR' },
      status: 'trialing',
      trial_ends_at: '2026-08-16T19:00:00.000Z',
      current_period_end: null,
    })
    wrap()

    // Rendered from the UTC instant rather than counted in local days: PKT is
    // UTC+5, so a local date subtraction is off by one for part of every day.
    await waitFor(() => expect(screen.getByText(/free trial runs until/i)).toBeVisible())
  })

  it('fails closed when there is no subscription record at all', async () => {
    // prd.md MON-2: an absent record means no access, never an implied trial.
    apiFetch.mockRejectedValue(new ApiError(403, 'SUBSCRIPTION_REQUIRED', 'none'))
    wrap()

    await waitFor(() => expect(screen.getByText(en.plan.noAccess)).toBeVisible())
    expect(screen.queryByText(/free trial runs until/i)).not.toBeInTheDocument()
    // Not an error banner: choosing the plan is the fix, and it is on screen.
    expect(screen.queryByText(en.auth.errors.generic)).not.toBeInTheDocument()
  })
})

describe('selecting the plan', () => {
  it('posts the selection and moves on to the dashboard', async () => {
    const user = userEvent.setup()
    apiFetch.mockResolvedValue({
      plan: { code: 'standard', name: 'EduBridge AI', price_minor: 99900, currency: 'PKR' },
      status: 'trialing',
      trial_ends_at: null,
      current_period_end: null,
    })
    wrap()

    await waitFor(() => expect(screen.getByText(en.plan.statusTitle)).toBeVisible())
    await user.click(screen.getByRole('button', { name: new RegExp(en.plan.select, 'i') }))

    expect(apiFetch).toHaveBeenCalledWith('/subscription/select', {
      method: 'POST',
      body: { plan: 'standard' },
    })
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'))
  })
})
