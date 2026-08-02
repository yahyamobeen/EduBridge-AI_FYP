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

export function routeForOnboardingState(state: OnboardingState, role: Role): string {
  switch (state) {
    case 'email_verification_pending':
      return '/onboarding/email'
    case 'two_factor_enrollment_pending':
      return '/onboarding/2fa'
    case 'guardian_link_pending':
      return '/onboarding/guardian'
    case 'plan_selection_pending':
      return '/onboarding/plan'
    case 'active':
      return dashboardFor(role)
  }
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
