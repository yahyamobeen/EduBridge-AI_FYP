import { describe, expect, it } from 'vitest'
import type { OnboardingState, Role } from '@/lib/api/types'
import { dashboardFor, isOnboardingComplete, routeForOnboardingState } from './onboarding'

const STATES: OnboardingState[] = [
  'email_verification_pending',
  'two_factor_enrollment_pending',
  'guardian_link_pending',
  'plan_selection_pending',
  'active',
]

const ROLES: Role[] = ['student', 'teacher', 'parent', 'admin']

describe('routeForOnboardingState', () => {
  it('returns a route for every state and role combination', () => {
    for (const state of STATES) {
      for (const role of ROLES) {
        expect(routeForOnboardingState(state, role), `${state}/${role}`).toMatch(/^\//)
      }
    }
  })

  it('sends incomplete onboarding to its step regardless of role', () => {
    for (const role of ROLES) {
      expect(routeForOnboardingState('email_verification_pending', role)).toBe(
        '/onboarding/email',
      )
      expect(routeForOnboardingState('two_factor_enrollment_pending', role)).toBe(
        '/onboarding/2fa',
      )
      expect(routeForOnboardingState('guardian_link_pending', role)).toBe(
        '/onboarding/guardian',
      )
      expect(routeForOnboardingState('plan_selection_pending', role)).toBe('/onboarding/plan')
    }
  })

  it('sends an active user to their own dashboard', () => {
    expect(routeForOnboardingState('active', 'student')).toBe('/dashboard')
    expect(routeForOnboardingState('active', 'teacher')).toBe('/teacher')
    expect(routeForOnboardingState('active', 'parent')).toBe('/parent')
  })

  it('gives each role a distinct dashboard so none can leak into another', () => {
    const routes = ROLES.map(dashboardFor)
    expect(new Set(routes).size).toBe(ROLES.length)
  })
})

describe('isOnboardingComplete', () => {
  it('is true only for active', () => {
    for (const state of STATES) {
      expect(isOnboardingComplete(state)).toBe(state === 'active')
    }
  })

  it('treats plan_selection_pending as incomplete even though it follows active', () => {
    // The non-monotonic transition (prd.md MON-4): a guard that caches `active`
    // would keep a lapsed-trial student on a page they no longer have rights to.
    expect(isOnboardingComplete('plan_selection_pending')).toBe(false)
  })
})
