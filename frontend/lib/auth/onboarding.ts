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

/**
 * ⚠️ FINDING D6 — THE TYPE IS NOT A CHECK, AND THIS IS THE BOUNDARY.
 *
 * `OnboardingState` is a compile-time union. The value reaching these functions
 * came from a JSON response, so TypeScript's guarantee stops at the network:
 * a backend that returned a state this table does not list — a new one, a typo,
 * a stale deployment — produced `ONBOARDING_ROUTES[state] === undefined`, and
 * the caller then did `router.replace(undefined)`.
 *
 * That does not throw. Next's router treats it as a navigation to nowhere, so
 * the user sits on a screen that has decided to move them and never does, with
 * nothing in the console. Validating here is cheap and turns an invisible hang
 * into a visible failure.
 *
 * Falling back to the dashboard rather than throwing: an unknown state is a
 * server-side problem the user cannot act on, and stranding them is worse than
 * showing them something. The console line is for whoever has to find out why.
 */
function assertKnownState(state: OnboardingState): state is Exclude<OnboardingState, 'active'> {
  if (state in ONBOARDING_ROUTES) return true
  console.error('[onboarding] unroutable onboarding_state from the API:', state)
  return false
}

export function routeForOnboardingState(state: OnboardingState, role: Role): string {
  if (state === 'active') return dashboardFor(role)
  return assertKnownState(state) ? ONBOARDING_ROUTES[state] : dashboardFor(role)
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
  if (state === 'active') return null
  // `null` for an unknown state, not `undefined`: every caller already handles
  // "no step left", and that path leaves the user where they are rather than
  // navigating nowhere. See `assertKnownState` above for why this is checked at
  // all when the type says it cannot happen.
  return assertKnownState(state) ? ONBOARDING_ROUTES[state] : null
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
