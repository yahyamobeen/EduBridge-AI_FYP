import { describe, expect, it } from 'vitest'
import {
  deriveOnboardingState,
  ENUMS,
  guardianRequiredFor,
  seedUsers,
  type MockUser,
} from './db'

function userNamed(id: string): MockUser {
  const user = seedUsers().find((u) => u.id === id)
  if (!user) throw new Error(`no seeded user ${id}`)
  return user
}

describe('onboarding derivation', () => {
  it('asks for email verification first', () => {
    expect(deriveOnboardingState(userNamed('u-unverified'))).toBe('email_verification_pending')
  })

  it('asks for a second factor once the email is verified', () => {
    expect(deriveOnboardingState(userNamed('u-no2fa'))).toBe('two_factor_enrollment_pending')
  })

  it('gates a Class 9 student without a verified guardian', () => {
    expect(deriveOnboardingState(userNamed('u-gate'))).toBe('guardian_link_pending')
  })

  it('never gates a Class 11 student', () => {
    // The gate must be unreachable for 11-12, not merely hidden.
    const s11 = userNamed('u-s11')
    expect(s11.guardian.required).toBe(false)
    expect(deriveOnboardingState(s11)).toBe('active')
  })

  it('lets a fully onboarded student through while the trial runs', () => {
    expect(deriveOnboardingState(userNamed('u-s9'))).toBe('active')
  })

  it('returns an otherwise-complete student to plan selection once the trial lapses', () => {
    // The non-monotonic transition (prd.md MON-4).
    expect(deriveOnboardingState(userNamed('u-expired'))).toBe('plan_selection_pending')
  })

  it('treats a missing subscription as no access, never as an open trial', () => {
    // prd.md MON-2: a failed insert must not grant free access forever.
    const user = { ...userNamed('u-s9'), subscription: null }
    expect(deriveOnboardingState(user)).toBe('plan_selection_pending')
  })

  it('never asks a teacher or parent to choose a plan', () => {
    for (const id of ['u-teacher', 'u-parent']) {
      expect(deriveOnboardingState(userNamed(id)), id).toBe('active')
    }
  })

  it('flips an active student to plan selection as the trial boundary passes', () => {
    const user = userNamed('u-s9')
    const endsAt = Date.parse(user.subscription?.trial_ends_at ?? '')
    expect(deriveOnboardingState(user, endsAt - 1000)).toBe('active')
    expect(deriveOnboardingState(user, endsAt + 1000)).toBe('plan_selection_pending')
  })
})

describe('guardianRequiredFor', () => {
  it('is true only for students in Classes 9 and 10', () => {
    expect(guardianRequiredFor('student', 9)).toBe(true)
    expect(guardianRequiredFor('student', 10)).toBe(true)
    expect(guardianRequiredFor('student', 11)).toBe(false)
    expect(guardianRequiredFor('student', 12)).toBe(false)
    expect(guardianRequiredFor('teacher', 9)).toBe(false)
    expect(guardianRequiredFor('parent', undefined)).toBe(false)
  })
})

describe('reference enums', () => {
  it('keys groups by class as a string, matching the contract', () => {
    expect(ENUMS.groups_by_class['9']).toBeDefined()
    expect(Object.keys(ENUMS.groups_by_class)).toEqual(['9', '10', '11', '12'])
  })

  it('pins where the string/number key mismatch actually bites', () => {
    // Bracket access is SAFE: JavaScript coerces the key, so both forms are the
    // same lookup. Comparison is where it silently fails, in both directions --
    // which is what signup must normalise around.
    const keys = Object.keys(ENUMS.groups_by_class)
    const nine = ENUMS.class_levels[0]

    expect(ENUMS.groups_by_class[9 as unknown as string]).toEqual(ENUMS.groups_by_class['9'])
    expect(keys.includes(nine as unknown as string)).toBe(false)
    expect(new Set(keys).has(nine as unknown as string)).toBe(false)
    expect(ENUMS.class_levels.includes('9' as unknown as number)).toBe(false)

    // The safe form.
    expect(keys.includes(String(nine))).toBe(true)
  })

  it('offers groups for every advertised class level', () => {
    for (const level of ENUMS.class_levels) {
      const groups = ENUMS.groups_by_class[String(level)]
      expect(groups, `class ${level}`).toBeDefined()
      expect(groups?.length).toBeGreaterThan(0)
    }
  })

  it('offers different groups to Matric and FSc classes', () => {
    const matric = ENUMS.groups_by_class['9']?.map((g) => g.code)
    const fsc = ENUMS.groups_by_class['11']?.map((g) => g.code)
    expect(matric).toEqual(['science', 'computer'])
    expect(fsc).toEqual(['pre_medical', 'pre_engineering', 'ics'])
    // A group valid for Class 9 must not be accepted for Class 11.
    expect(fsc).not.toContain('science')
  })
})
