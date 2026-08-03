/**
 * Contract types, transcribed from tdd.md §3.1 (endpoint table) and §7.3.
 *
 * The mock layer and the live client both build on these, so a mock that
 * drifts from the contract is a type error rather than a runtime surprise
 * discovered during integration (tdd.md §3.10).
 */

export type Role = 'student' | 'teacher' | 'parent' | 'admin'

/** Derived server-side per request; never stored. Precedence in tdd.md §3.1. */
export type OnboardingState =
  | 'email_verification_pending'
  | 'two_factor_enrollment_pending'
  | 'guardian_link_pending'
  | 'plan_selection_pending'
  | 'active'

export type BoardCode = 'PCTB' | 'STBB'
export type StudentGroup = 'science' | 'computer' | 'pre_medical' | 'pre_engineering' | 'ics'
export type Medium = 'en' | 'ur'

/** The `language_code` enum. NOT a web locale -- see i18n/routing.ts. */
export type ApiLanguage = 'en' | 'ur' | 'roman_ur'

export type TwoFactorMethod = 'totp' | 'email_otp'
export type TwoFactorType = TwoFactorMethod | 'backup_code'
export type GuardianStatus = 'pending' | 'verified' | 'revoked'
export type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'canceled' | 'expired'

// ---------------------------------------------------------------------------
// Reference data
// ---------------------------------------------------------------------------

export type EnumsResponse = {
  boards: Array<{ code: BoardCode; name: string }>
  class_levels: number[]
  /**
   * Keyed by class level as a STRING, while `class_levels` are NUMBERS.
   *
   * Bracket access is safe -- JavaScript coerces the key, so `[9]` and `['9']`
   * are the same lookup. What breaks is COMPARING the two, in either
   * direction, because no coercion happens there:
   *
   *   Object.keys(groups_by_class).includes(9)   -> false
   *   new Set(Object.keys(...)).has(9)           -> false
   *   new Map(Object.entries(...)).get(9)        -> undefined
   *   class_levels.includes('9')                 -> false
   *
   * So normalise with String() before any comparison or collection lookup.
   */
  groups_by_class: Record<string, Array<{ code: StudentGroup; label: string }>>
  mediums: Medium[]
  languages: ApiLanguage[]
}

// ---------------------------------------------------------------------------
// Registration and sign-in
// ---------------------------------------------------------------------------

export type RegisterRequest = {
  email: string
  password: string
  full_name: string
  role: Exclude<Role, 'admin'>
  // Students only.
  board?: BoardCode
  class_level?: number
  student_group?: StudentGroup
  medium?: Medium
  language_pref?: ApiLanguage
}

/** No token: the account starts at `email_verification_pending` (tdd.md §3.1). */
export type RegisterResponse = {
  user_id: string
  email: string
  role: Role
  onboarding_state: OnboardingState
}

export type LoginRequest = { email: string; password: string }

/**
 * A 200 is NEVER a credential failure -- it means the request succeeded and the
 * journey is simply incomplete. Branch on `status`; only a 401 means the
 * password was wrong (tdd.md §3.1).
 */
export type LoginResponse =
  | {
      status: 'two_factor_required'
      pending_token: string
      method: TwoFactorMethod
      expires_in: number
    }
  | { status: 'two_factor_enrollment_required'; enrollment_token: string; expires_in: number }
  | { status: 'email_verification_required'; email: string }

export type LoginStatus = LoginResponse['status']

// ---------------------------------------------------------------------------
// Two-factor
// ---------------------------------------------------------------------------

export type TwoFactorVerifyRequest = {
  pending_token: string
  code: string
  type: TwoFactorType
}

/** Re-sends an email OTP for an ALREADY email-OTP-enrolled challenge (tdd.md §3.1). */
export type TwoFactorResendRequest = { pending_token: string }

export type TwoFactorResendResponse = { sent_to: string; expires_in: number }

export type TwoFactorVerifyResponse = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  onboarding_state: OnboardingState
}

/** `enrollment_token` travels in the body, matching `pending_token` (tdd.md §3.1). */
export type TwoFactorEnrollRequest = {
  method: TwoFactorMethod
  enrollment_token: string
}

export type TwoFactorEnrollResponse =
  | {
      method: 'totp'
      secret: string
      otpauth_uri: string
      /** Server-rendered SVG. Render as a data-URI <img>, never as HTML (tdd.md §6.11). */
      qr_svg: string
    }
  | { method: 'email_otp'; sent_to: string; expires_in: number }

export type TwoFactorConfirmRequest = { code: string; enrollment_token: string }

export type TwoFactorConfirmResponse = {
  two_factor: { enabled: boolean; method: TwoFactorMethod }
  /** Shown exactly once. 8 alphanumeric characters, compared case-insensitively. */
  backup_codes: string[]
  onboarding_state: OnboardingState
  /** Added in v0.3.2 so enrolling does not force an immediate second login. */
  access_token: string
  expires_in: number
}

// ---------------------------------------------------------------------------
// Email and password
// ---------------------------------------------------------------------------

export type EmailVerifyRequest = { token: string }

export type EmailVerifyResponse = {
  email_verified: boolean
  onboarding_state: OnboardingState
  /** Scoped to onboarding routes only -- not a general session (tdd.md §3.1). */
  access_token: string
  expires_in: number
  enrollment_token: string
}

export type EmailResendRequest = { email: string }
export type PasswordForgotRequest = { email: string }
export type PasswordResetRequest = { token: string; new_password: string }

// ---------------------------------------------------------------------------
// Guardian gate
// ---------------------------------------------------------------------------

export type GuardianInviteRequest = { parent_email: string }

export type GuardianInviteResponse = {
  invite_sent: boolean
  parent_email: string
  status: GuardianStatus
}

/**
 * ASSUMPTION, flagged for Mujtaba. `guardian/confirm` is authenticated as the
 * parent (tdd.md §3.1) but the request body is not specified anywhere. The
 * invite link has to identify WHICH pending link is being confirmed, otherwise
 * a parent with two children cannot say which one — so the token from the email
 * travels in the body, matching the rule that a token is always a body field
 * (decision 6). If Mujtaba's implementation keys off the parent's identity
 * alone, this field is dropped and nothing else changes.
 */
export type GuardianConfirmRequest = { invite_token: string }

export type GuardianConfirmResponse = {
  status: GuardianStatus
  /** Nullable: `app_user.full_name` is, and `MeResponse.full_name` already says so. */
  student_name: string | null
}

export type GuardianStatusResponse = {
  required: boolean
  status: GuardianStatus | null
  parent_email: string | null
  invited_at: string | null
}

// ---------------------------------------------------------------------------
// Identity and session
// ---------------------------------------------------------------------------

export type StudentProfile = {
  board: BoardCode
  class_level: number
  student_group: StudentGroup
  medium: Medium
  language_pref: ApiLanguage
}

export type MeResponse = {
  user_id: string
  email: string
  full_name: string
  role: Role
  onboarding_state: OnboardingState
  email_verified: boolean
  two_factor: { enabled: boolean; method: TwoFactorMethod | null }
  profile: StudentProfile | null
  guardian: { required: boolean; status: GuardianStatus | null }
}

export type RefreshResponse = { access_token: string; expires_in: number }

// ---------------------------------------------------------------------------
// Subscription
// ---------------------------------------------------------------------------

export type SubscriptionResponse = {
  plan: { code: string; name: string; price_minor: number; currency: string }
  status: SubscriptionStatus
  trial_ends_at: string | null
  current_period_end: string | null
}
