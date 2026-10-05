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
  // Required everywhere since the Turnstile rollout: the client proves
  // a human solved the widget before the server will touch the account.
  turnstile_token: string
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

export type LoginRequest = { email: string; password: string; turnstile_token: string }

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
  /**
   * NULLABLE, and it was typed `string` here while this very file said so
   * elsewhere: `GuardianConfirmResponse.student_name` carries the comment
   * "`app_user.full_name` is nullable, and `MeResponse.full_name` already says
   * so". It did not. The backend is `full_name: str | None`
   * (`schemas.py:225`) because the column is nullable
   * (`initial_schema.sql:103`), and `Guardian.test.tsx:188` records a 500 that
   * the same mistake caused on the confirm path.
   */
  full_name: string | null
  role: Role
  /**
   * ⚠️ TOP-LEVEL, because `profile` is `null` for three roles out of four.
   *
   * The column moved to `app_user` so every role could have a stored language,
   * and `PATCH /auth/me` accepts it from every role — but this response
   * originally carried it only inside `profile`, making it writable by four
   * roles and readable by one. A teacher who chose Urdu saw English.
   *
   * `profile.language_pref` still exists and reads the same column.
   */
  language_pref: ApiLanguage
  onboarding_state: OnboardingState
  email_verified: boolean
  two_factor: { enabled: boolean; method: TwoFactorMethod | null }
  profile: StudentProfile | null
  guardian: { required: boolean; status: GuardianStatus | null }
}

export type RefreshResponse = { access_token: string; expires_in: number }

// ---------------------------------------------------------------------------
// FR-A8 — manage own account. All three are authenticated.
// ---------------------------------------------------------------------------

/**
 * `full_name` and `language_pref` only.
 *
 * `board`, `class_level` and `student_group` are deliberately absent. Class
 * level is the parental-consent gate input, and board and group scope every
 * progress record a student has — the API rejects all three, and the settings
 * screen renders them read-only for the same reason.
 *
 * At least one field must be present; an empty object is a 400.
 */
export type MeUpdateRequest = {
  full_name?: string
  language_pref?: ApiLanguage
}

export type PasswordChangeRequest = {
  current_password: string
  new_password: string
}

/**
 * Never carries the secret. The view behind it was built without that column,
 * so this is structural rather than a field the type happens to omit.
 *
 * `locked_until` is an ISO-8601 instant, not a duration.
 */
export type TwoFactorStatusResponse = {
  enabled: boolean
  method: TwoFactorMethod | null
  locked_until: string | null
  backup_codes_remaining: number
}

// ---------------------------------------------------------------------------
// Subscription
// ---------------------------------------------------------------------------

export type SubscriptionResponse = {
  plan: { code: string; name: string; price_minor: number; currency: string }
  status: SubscriptionStatus
  trial_ends_at: string | null
  current_period_end: string | null
}

// ---------------------------------------------------------------------------
// Classroom (tdd.md §3.6) — mirrors backend/app/classroom/schemas.py
// ---------------------------------------------------------------------------

export type SpaceStatus = 'active' | 'archived'

export type SubjectRef = { id: string; name: string; board: BoardCode; class_level: number }

export type SpaceSummary = {
  id: string
  title: string
  status: SpaceStatus
  subject: SubjectRef
  owner_name: string | null
  /** Decided by the SERVER. Owner-only controls render from this, never from the role alone. */
  viewer_role: 'owner' | 'member'
  /** False for an owner whose subject scope an administrator revoked. */
  can_manage: boolean
  /** Owner only; null for members. */
  member_count: number | null
  /** Member only; null for the owner. */
  joined_at: string | null
}

export type SpaceDetail = SpaceSummary & {
  /** The live join code — the database returns it to a scoped owner only. */
  join_code: string | null
  /** While true only the teacher posts in the class chat (Phase 7). */
  chat_locked: boolean
}

export type SpaceListResponse = { spaces: SpaceSummary[] }

export type SpaceCreateRequest = { title: string; subject_id: string }

export type SpaceUpdateRequest = {
  title?: string
  status?: SpaceStatus
  chat_locked?: boolean
}

export type JoinCodeResponse = { join_code: string | null }

export type JoinResponse = { space_id: string; already_member: boolean }

/**
 * `details.reason` on a 400 VALIDATION_ERROR from POST /spaces/join (tdd.md
 * §7.3). Branch on this, never on `message`. A removed student deliberately
 * receives `invalid_code`.
 */
export type JoinFailureReason = 'invalid_code' | 'class_mismatch' | 'classroom_full'

/** `details.space` on a `class_mismatch` refusal — the student holds the code, so naming the class is not a leak. */
export type JoinMismatchSpace = {
  title: string
  subject_name: string
  board: BoardCode
  class_level: number
}

export type Person = { user_id: string; full_name: string | null }

export type Member = Person & {
  joined_at: string
  /** Owner's view only; null for members. */
  muted: boolean | null
}

export type PeopleResponse = { owner: Person; members: Member[] }

export type SubjectOption = { id: string; name: string; groups: StudentGroup[] }

export type SubjectsResponse = { subjects: SubjectOption[] }

// Phase 3 — the stream

export type Announcement = {
  id: string
  body: string
  author_id: string
  /** When members may see it. A future value means scheduled. */
  publish_at: string
  /** Only ever true in the owner's view: the database hides scheduled posts from members. */
  scheduled: boolean
  created_at: string
  updated_at: string
  /** Teacher attachments (Phase 6); a member sees them once the post is live. */
  attachments: FileMeta[]
}

export type AnnouncementPage = {
  items: Announcement[]
  /** Opaque keyset cursor for the next, older page; null at the end. */
  next_cursor: string | null
}

/** `publish_at` must be an ISO instant WITH an offset; omit it to post now. */
export type AnnouncementCreateRequest = { body: string; publish_at?: string }

export type AnnouncementUpdateRequest = { body?: string; publish_at?: string }

// Phase 4 — assignments, submissions and grades

/** Derived by the server from the timestamps on every read; never stored. */
export type WorkStatus = 'assigned' | 'turned_in' | 'turned_in_late' | 'missing' | 'graded'

export type ChapterRef = { id: string; number: number; title: string }

export type ChaptersResponse = { chapters: ChapterRef[] }

export type AssignmentSummary = {
  id: string
  title: string
  due_at: string | null
  points: number | null
  chapter: ChapterRef | null
  publish_at: string
  /** Only ever true in the owner's view, as for announcements. */
  scheduled: boolean
  /** Member view only; null for the owner. `my_grade` only once returned. */
  my_status: WorkStatus | null
  my_grade: number | null
  /** Owner view only; null for a member. */
  turned_in_count: number | null
}

export type AssignmentPage = { items: AssignmentSummary[]; next_cursor: string | null }

/** The calling student's own work. `grade` and `feedback` are null until returned. */
export type MySubmission = {
  body: string
  turned_in_at: string | null
  status: WorkStatus
  grade: number | null
  feedback: string | null
  returned_at: string | null
  /** The student's own uploaded files (Phase 6) and links (Phase 6b). */
  files: FileMeta[]
  links: LinkMeta[]
}

export type AssignmentDetail = AssignmentSummary & {
  space_id: string
  instructions: string
  created_at: string
  updated_at: string
  /** Member view only. */
  my_submission: MySubmission | null
  /** Teacher attachments (Phase 6). */
  attachments: FileMeta[]
}

/** Times are ISO instants WITH an offset (lib/datetime.ts). */
export type AssignmentCreateRequest = {
  title: string
  instructions?: string
  due_at?: string
  points?: number
  chapter_id?: string
  publish_at?: string
}

/** Send only what changed. `null` clears `due_at`, `points` or `chapter_id`. */
export type AssignmentUpdateRequest = {
  title?: string
  instructions?: string
  due_at?: string | null
  points?: number | null
  chapter_id?: string | null
  publish_at?: string
}

/** Links are their own rows since Phase 6b (`addSubmissionLink`). */
export type SubmissionDraftRequest = { body: string }

/**
 * `details.reason` on a 400 from the submission endpoints: `graded` — the
 * teacher has saved a grade, so the work is locked; `turned_in` — unsubmit first.
 */
export type SubmissionRefusalReason = 'graded' | 'turned_in'

export type GradeRequest = {
  grade: number | null
  feedback: string
  return_to_student: boolean
}

/** One row of the teacher's table: every active member, submitted or not. */
export type SubmissionRow = {
  student_id: string
  full_name: string | null
  status: WorkStatus
  turned_in_at: string | null
  grade: number | null
  returned_at: string | null
  /** A grade is saved (returned or not); the student's work is locked. */
  graded: boolean
}

export type SubmissionsResponse = { rows: SubmissionRow[] }

/** One student's work for the teacher. `body` is null until it is turned in. */
export type StudentWork = SubmissionRow & {
  body: string | null
  feedback: string
  /** Empty until the work is turned in, like `body`. */
  files: FileMeta[]
  links: LinkMeta[]
}

// Phase 5 — the calendar

export type CalendarItemKind = 'due' | 'scheduled_assignment' | 'scheduled_announcement'

export type CalendarItem = {
  kind: CalendarItemKind
  /** The deadline for `due`; the moment it goes live for a scheduled post. */
  at: string
  space_id: string
  space_title: string
  /** The assignment or announcement this entry is about. */
  ref_id: string
  title: string
  /** A student's own derived status, on `due` entries only. */
  my_status: WorkStatus | null
}

/** `truncated` is true when the range held more than the 500-entry cap. */
export type CalendarResponse = { items: CalendarItem[]; truncated: boolean }

// Phase 6 — files

/** A stored file. Its storage key never leaves the server. */
export type FileMeta = {
  id: string
  /** Sanitised by the server, with the extension forced to the detected type. */
  filename: string
  content_type: string
  size_bytes: number
  created_at: string
}

/**
 * `details.reason` on a 400 from the upload and delete endpoints. Branch on
 * this, never on `message`. `graded` and `turned_in` match the submission
 * refusals.
 */
export type FileRefusalReason =
  | 'unsupported_type'
  | 'too_large'
  | 'empty'
  | 'length_required'
  | 'length_mismatch'
  | 'too_many_files'
  | 'submission_quota'
  | 'classroom_quota'
  | 'graded'
  | 'turned_in'
  /** A view link was asked for an Office file: those are download-only. */
  | 'not_viewable'

// Phase 6b — links on a piece of work, and viewing in the browser

/** A link on a student's work. The server stores `https://` links only. */
export type LinkMeta = {
  id: string
  url: string
  created_at: string
}

/**
 * `details.reason` on a 400 from the link endpoints. A malformed link is
 * `details.fields.url` instead.
 */
export type LinkRefusalReason = 'too_many_links' | 'graded' | 'turned_in'

/**
 * A short-lived link that shows a PDF or an image in a new tab, on the storage
 * service's own domain. A bearer pass until `expires_at`: open it, never keep it.
 */
export type ViewLink = { url: string; expires_at: string }

// Phase 7 — the class chat

/** One message in a classroom's chat. Plain text: never rendered as HTML. */
export type ChatMessage = {
  id: string
  author_id: string
  body: string
  created_at: string
  /** True only in the teacher's view: a member never receives a deleted message. */
  deleted: boolean
}

/** GET /spaces/{id}/messages. */
export type ChatPage = {
  /** Oldest first. */
  messages: ChatMessage[]
  /** Deleted since `after` — remove them (a member), or mark them deleted (the teacher). */
  deleted_ids: string[]
  /** Pass as `before` for the page of older messages; null when there are none. */
  older_cursor: string | null
  /** The DATABASE clock: the next poll's `after`. */
  server_time: string
  /** The catch-up was too far behind: replace what is shown with `messages`. */
  reset: boolean
  chat_locked: boolean
  can_post: boolean
  /** The caller's own mute, so the screen can say why they cannot post. */
  muted: boolean
}

/** `details.reason` on a 400 from POST /spaces/{id}/messages. */
export type ChatRefusalReason = 'archived' | 'muted' | 'chat_locked'
