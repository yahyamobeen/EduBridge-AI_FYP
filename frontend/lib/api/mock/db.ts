import type {
  ApiLanguage,
  BoardCode,
  EnumsResponse,
  GuardianStatus,
  Medium,
  OnboardingState,
  Role,
  StudentGroup,
  SubscriptionStatus,
  TwoFactorMethod,
} from '../types'

/** Seeded, in-memory, dev-only. Never bundled into a live build (client.ts). */

export type MockUser = {
  id: string
  email: string
  password: string
  full_name: string
  role: Role
  email_verified_at: string | null
  two_factor: { status: 'pending' | 'active' | 'disabled'; method: TwoFactorMethod | null }
  profile: {
    board: BoardCode
    class_level: number
    student_group: StudentGroup
    medium: Medium
    language_pref: ApiLanguage
  } | null
  guardian: {
    required: boolean
    status: GuardianStatus | null
    parent_email: string | null
    invited_at: string | null
  }
  subscription: { status: SubscriptionStatus; trial_ends_at: string | null } | null
  backup_codes: string[]
}

const DAY_MS = 86_400_000

function daysFromNow(days: number): string {
  return new Date(Date.now() + days * DAY_MS).toISOString()
}

/**
 * The precedence from tdd.md §3.1, reproduced exactly.
 *
 * Rule 4 can fire AFTER a user has been active -- that is the non-monotonic
 * transition (prd.md MON-4), and reproducing it here is what makes the
 * behaviour testable before the backend exists.
 */
export function deriveOnboardingState(user: MockUser, now = Date.now()): OnboardingState {
  if (user.email_verified_at === null) return 'email_verification_pending'
  if (user.two_factor.status !== 'active') return 'two_factor_enrollment_pending'

  if (user.role === 'student') {
    if (user.guardian.required && user.guardian.status !== 'verified') {
      return 'guardian_link_pending'
    }
    // Fail closed: no subscription record is NOT a trial (prd.md MON-2).
    const sub = user.subscription
    if (sub === null) return 'plan_selection_pending'
    if (sub.status === 'trialing') {
      const endsAt = sub.trial_ends_at === null ? 0 : Date.parse(sub.trial_ends_at)
      if (now >= endsAt) return 'plan_selection_pending'
    } else if (sub.status !== 'active') {
      return 'plan_selection_pending'
    }
  }

  return 'active'
}

/** Class 9-10 require a verified guardian; 11-12 never do (prd.md §4.3). */
export function guardianRequiredFor(role: Role, classLevel: number | undefined): boolean {
  return role === 'student' && (classLevel === 9 || classLevel === 10)
}

function student(
  over: Partial<MockUser> & Pick<MockUser, 'id' | 'email'>,
  classLevel: number,
  group: StudentGroup,
): MockUser {
  return {
    password: 'Password123',
    full_name: 'Test Student',
    role: 'student',
    email_verified_at: new Date(Date.now() - DAY_MS).toISOString(),
    two_factor: { status: 'active', method: 'totp' },
    profile: {
      board: 'PCTB',
      class_level: classLevel,
      student_group: group,
      medium: 'en',
      language_pref: 'en',
    },
    guardian: {
      required: guardianRequiredFor('student', classLevel),
      status: classLevel <= 10 ? 'verified' : null,
      parent_email: classLevel <= 10 ? 'p***@example.com' : null,
      invited_at: null,
    },
    subscription: { status: 'trialing', trial_ends_at: daysFromNow(14) },
    backup_codes: [],
    ...over,
  }
}

/** Personas chosen to cover each branch of the derivation above. */
export function seedUsers(): MockUser[] {
  return [
    // Class 9, gate satisfied, trial running -> active.
    student(
      { id: 'u-s9', email: 'student9@example.com', full_name: 'Aisha Khan' },
      9,
      'science',
    ),

    // Class 9, gate NOT satisfied -> guardian_link_pending.
    student(
      {
        id: 'u-gate',
        email: 'gate@example.com',
        full_name: 'Bilal Ahmed',
        guardian: { required: true, status: null, parent_email: null, invited_at: null },
      },
      9,
      'science',
    ),

    // Class 11 -> must NEVER see the gate.
    student(
      { id: 'u-s11', email: 'student11@example.com', full_name: 'Sana Iqbal' },
      11,
      'pre_medical',
    ),

    // Trial already lapsed -> plan_selection_pending, even though everything
    // else is complete. This is the non-monotonic case.
    student(
      {
        id: 'u-expired',
        email: 'expired@example.com',
        full_name: 'Hamza Ali',
        subscription: { status: 'trialing', trial_ends_at: daysFromNow(-1) },
      },
      11,
      'ics',
    ),

    // Never verified their email.
    student(
      {
        id: 'u-unverified',
        email: 'unverified@example.com',
        full_name: 'Zara Malik',
        email_verified_at: null,
        two_factor: { status: 'pending', method: null },
      },
      10,
      'computer',
    ),

    // Verified, but has not enrolled a second factor.
    student(
      {
        id: 'u-no2fa',
        email: 'no2fa@example.com',
        full_name: 'Usman Tariq',
        two_factor: { status: 'pending', method: null },
      },
      12,
      'pre_engineering',
    ),

    {
      id: 'u-teacher',
      email: 'teacher@example.com',
      password: 'Password123',
      full_name: 'Mr Rehman',
      role: 'teacher',
      email_verified_at: new Date(Date.now() - DAY_MS).toISOString(),
      two_factor: { status: 'active', method: 'email_otp' },
      profile: null,
      guardian: { required: false, status: null, parent_email: null, invited_at: null },
      subscription: null,
      backup_codes: [],
    },

    {
      id: 'u-parent',
      email: 'parent@example.com',
      password: 'Password123',
      full_name: 'Mrs Khan',
      role: 'parent',
      email_verified_at: new Date(Date.now() - DAY_MS).toISOString(),
      two_factor: { status: 'active', method: 'email_otp' },
      profile: null,
      guardian: { required: false, status: null, parent_email: null, invited_at: null },
      subscription: null,
      backup_codes: [],
    },
  ]
}

/** Matches prd.md §2.4.1: groups depend on the class, and are keyed by string. */
export const ENUMS: EnumsResponse = {
  boards: [
    { code: 'PCTB', name: 'Punjab Curriculum and Textbook Board' },
    { code: 'STBB', name: 'Sindh Textbook Board' },
  ],
  class_levels: [9, 10, 11, 12],
  groups_by_class: {
    '9': [
      { code: 'science', label: 'Science' },
      { code: 'computer', label: 'Computer Science' },
    ],
    '10': [
      { code: 'science', label: 'Science' },
      { code: 'computer', label: 'Computer Science' },
    ],
    '11': [
      { code: 'pre_medical', label: 'Pre-Medical' },
      { code: 'pre_engineering', label: 'Pre-Engineering' },
      { code: 'ics', label: 'ICS' },
    ],
    '12': [
      { code: 'pre_medical', label: 'Pre-Medical' },
      { code: 'pre_engineering', label: 'Pre-Engineering' },
      { code: 'ics', label: 'ICS' },
    ],
  },
  mediums: ['en', 'ur'],
  languages: ['en', 'ur', 'roman_ur'],
}

export const PLAN = {
  code: 'standard',
  name: 'EduBridge AI',
  price_minor: 99_900,
  currency: 'PKR',
} as const

/** Masks an address the way the contract does: s***@example.com */
export function maskEmail(email: string): string {
  const [local = '', domain = ''] = email.split('@')
  return `${local.slice(0, 1)}***@${domain}`
}
