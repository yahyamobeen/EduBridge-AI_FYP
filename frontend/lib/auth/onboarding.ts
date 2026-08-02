import type { OnboardingState, Role } from '@/lib/api/types'

/**
 * The ONE place onboarding routing is decided.
 *
 * Routing is driven by `onboarding_state` from the identity endpoint and
 * nothing else -- never from `class_level`, never from a combination of
 * booleans. That is also why a Class 11-12 student has no code path that can
 * render the parental gate: the backend never sets the state for them, so the
 * frontend has nothing to render it from (tdd.md §3.1, §3.10).
 */

export const DASHBOARD_BY_ROLE: Record<Role, string> = {
  student: '/dashboard',
  teacher: '/teacher',
  parent: '/parent',
  admin: '/admin',
}

export function dashboardFor(role: Role): string {
  return DASHBOARD_BY_ROLE[role]
}

const ONBOARDING_ROUTES: Record<Exclude<OnboardingState, 'active'>, string> = {
  email_verification_pending: '/onboarding/email',
  two_factor_enrollment_pending: '/onboarding/2fa',
  guardian_link_pending: '/onboarding/guardian',
  plan_selection_pending: '/onboarding/plan',
}

export function routeForOnboardingState(state: OnboardingState, role: Role): string {
  return state === 'active' ? dashboardFor(role) : ONBOARDING_ROUTES[state]
}

/**
 * The next onboarding step, or `null` when there is none left.
 *
 * Exists so a caller that has an `onboarding_state` but no `role` -- the 2FA
 * challenge, whose response carries the state and nothing else -- can route
 * without inventing a role. Only the `active` case needs one, and only then is
 * it worth a round trip to the identity endpoint to find out.
 */
export function pendingOnboardingRoute(state: OnboardingState): string | null {
  return state === 'active' ? null : ONBOARDING_ROUTES[state]
}

/**
 * Onboarding is NOT monotonic: a student who is `active` returns to
 * `plan_selection_pending` when the trial lapses (prd.md §2.6 MON-4). So this
 * must be re-evaluated on every identity check -- a guard that decides once and
 * then caches `active` will strand that user on a page they no longer have
 * rights to.
 */
export function isOnboardingComplete(state: OnboardingState): boolean {
  return state === 'active'
}
