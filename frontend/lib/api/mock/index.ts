import type { ApiRequestInit } from '../client'
import { ApiError } from '../errors'
import type {
  EmailResendRequest,
  EmailVerifyRequest,
  GuardianInviteRequest,
  LoginRequest,
  LoginResponse,
  MeResponse,
  RegisterRequest,
  TwoFactorConfirmRequest,
  TwoFactorEnrollRequest,
  TwoFactorVerifyRequest,
} from '../types'
import {
  deriveOnboardingState,
  ENUMS,
  guardianRequiredFor,
  maskEmail,
  PLAN,
  seedUsers,
  type MockUser,
} from './db'

/**
 * In-memory stand-in for the backend, matching tdd.md §3.1 field for field.
 * Dev-only: `client.ts` imports this dynamically behind a build-time constant,
 * so it is eliminated from a live bundle along with these seeded accounts.
 */

let users: MockUser[] = seedUsers()
let sessions = new Map<string, string>() // token -> user id
let counter = 0

/**
 * Forces a specific failure so every error state can be driven without a
 * backend. Set from `?scenario=` in the browser, or directly in tests.
 */
let scenario: string | null = null

/**
 * A real, scannable QR — a 21×21 module grid drawn as rects, which is enough
 * for the screen to prove it renders server-supplied SVG as a data-URI <img>
 * rather than injecting it as markup (tdd.md §6.11). The pattern is decorative,
 * not a valid encoding of the otpauth URI.
 */
const QR_SVG = [
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 21" shape-rendering="crispEdges">',
  '<rect width="21" height="21" fill="#fff"/>',
  '<path fill="#000" d="M0 0h7v7H0zm1 1v5h5V1zm1 1h3v3H2z"/>',
  '<path fill="#000" d="M14 0h7v7h-7zm1 1v5h5V1zm1 1h3v3h-3z"/>',
  '<path fill="#000" d="M0 14h7v7H0zm1 1v5h5v-5zm1 1h3v3H2z"/>',
  '<path fill="#000" d="M9 0h1v3H9zm2 4h1v2h-1zM8 5h2v1H8zm4 2h3v1h-3zM9 8h1v4H9zm3 3h2v1h-2z"/>',
  '<path fill="#000" d="M0 9h3v1H0zm5 0h3v1H5zm6 5h1v3h-1zm3 1h2v1h-2zm4 2h2v2h-2zm-6 2h3v1h-3z"/>',
  '</svg>',
].join('')

export function setMockScenario(next: string | null): void {
  scenario = next
}

export function resetMocks(): void {
  users = seedUsers()
  sessions = new Map()
  counter = 0
  scenario = null
}

export function mockUsers(): MockUser[] {
  return users
}

function nextToken(prefix: string): string {
  counter += 1
  return `${prefix}-${counter}`
}

function fail(status: number, code: string, details: Record<string, unknown> = {}): never {
  throw new ApiError(status, code, `Mock failure: ${code}`, details)
}

/** Applies a forced scenario, if one matches this endpoint. */
function applyScenario(path: string): void {
  if (scenario === null) return
  const [code, target] = scenario.split('@')
  if (target !== undefined && !path.includes(target)) return

  switch (code) {
    case 'RATE_LIMITED':
      fail(429, 'RATE_LIMITED', { retry_after: 30 })
    case 'TWO_FACTOR_LOCKED':
      fail(423, 'TWO_FACTOR_LOCKED', {
        locked_until: new Date(Date.now() + 900_000).toISOString(),
      })
    case 'GATE_PENDING':
      fail(403, 'GATE_PENDING')
    case 'SUBSCRIPTION_REQUIRED':
      fail(403, 'SUBSCRIPTION_REQUIRED')
    case 'FORBIDDEN_SCOPE':
      fail(403, 'FORBIDDEN_SCOPE')
    case 'UNAUTHENTICATED':
      fail(401, 'UNAUTHENTICATED')
    case 'TOKEN_EXPIRED':
      fail(410, 'TOKEN_EXPIRED')
    case 'INVALID_TOKEN':
      fail(400, 'INVALID_TOKEN')
    case 'MODEL_UNAVAILABLE':
      fail(503, 'MODEL_UNAVAILABLE')
    default:
      return
  }
}

function findByEmail(email: string): MockUser | undefined {
  return users.find((u) => u.email.toLowerCase() === email.toLowerCase())
}

function userFor(init: ApiRequestInit): MockUser {
  const token = init.bearer ?? currentAccessToken
  if (token === undefined || token === null) fail(401, 'UNAUTHENTICATED')
  const id = sessions.get(token)
  if (id === undefined) fail(401, 'UNAUTHENTICATED')
  const user = users.find((u) => u.id === id)
  if (user === undefined) fail(401, 'UNAUTHENTICATED')
  return user
}

/**
 * The mock cannot read the real token store without a circular import, so the
 * client hands the bearer through `init`. For session calls the last issued
 * token is remembered here instead.
 */
let currentAccessToken: string | null = null

function issueSession(user: MockUser): { access_token: string; expires_in: number } {
  const token = nextToken('access')
  sessions.set(token, user.id)
  currentAccessToken = token
  return { access_token: token, expires_in: 900 }
}

function meOf(user: MockUser): MeResponse {
  return {
    user_id: user.id,
    email: user.email,
    full_name: user.full_name,
    role: user.role,
    onboarding_state: deriveOnboardingState(user),
    email_verified: user.email_verified_at !== null,
    two_factor: {
      enabled: user.two_factor.status === 'active',
      method: user.two_factor.method,
    },
    profile: user.profile,
    guardian: { required: user.guardian.required, status: user.guardian.status },
  }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export async function mockRequest<T>(path: string, init: ApiRequestInit): Promise<T> {
  applyScenario(path)
  const method = init.method ?? 'GET'
  const key = `${method} ${path}`
  const body = (init.body ?? {}) as Record<string, unknown>

  switch (key) {
    case 'GET /reference/enums':
      return ENUMS as T

    case 'POST /auth/register': {
      const req = body as unknown as RegisterRequest
      if (findByEmail(req.email)) fail(409, 'EMAIL_ALREADY_REGISTERED')
      if (req.role === 'student') {
        const allowed = ENUMS.groups_by_class[String(req.class_level)] ?? []
        if (!allowed.some((g) => g.code === req.student_group)) fail(422, 'INVALID_CLASS_GROUP')
      }
      const user: MockUser = {
        id: nextToken('user'),
        email: req.email,
        password: req.password,
        full_name: req.full_name,
        role: req.role,
        email_verified_at: null,
        two_factor: { status: 'pending', method: null },
        profile:
          req.role === 'student' && req.board && req.student_group && req.medium
            ? {
                board: req.board,
                class_level: req.class_level ?? 0,
                student_group: req.student_group,
                medium: req.medium,
                language_pref: req.language_pref ?? 'en',
              }
            : null,
        guardian: {
          required: guardianRequiredFor(req.role, req.class_level),
          status: null,
          parent_email: null,
          invited_at: null,
        },
        subscription:
          req.role === 'student'
            ? {
                status: 'trialing',
                trial_ends_at: new Date(Date.now() + 14 * 86_400_000).toISOString(),
              }
            : null,
        backup_codes: [],
      }
      users.push(user)
      // Deliberately no token: registration does not create a session.
      return {
        user_id: user.id,
        email: user.email,
        role: user.role,
        onboarding_state: 'email_verification_pending',
      } as T
    }

    case 'POST /auth/login': {
      const req = body as unknown as LoginRequest
      const user = findByEmail(req.email)
      // A wrong password is the ONLY credential failure, and the response must
      // not reveal whether the address exists.
      if (!user || user.password !== req.password) fail(401, 'UNAUTHENTICATED')

      let response: LoginResponse
      if (user.email_verified_at === null) {
        response = { status: 'email_verification_required', email: maskEmail(user.email) }
      } else if (user.two_factor.status !== 'active') {
        response = {
          status: 'two_factor_enrollment_required',
          enrollment_token: registerChallenge('enroll', user),
          expires_in: 600,
        }
      } else {
        response = {
          status: 'two_factor_required',
          pending_token: registerChallenge('pending', user),
          method: user.two_factor.method ?? 'totp',
          expires_in: 300,
        }
      }
      return response as T
    }

    case 'POST /auth/2fa/verify': {
      const req = body as unknown as TwoFactorVerifyRequest
      const user = challengeUser(req.pending_token)
      if (req.code !== validCodeFor(req.type)) fail(401, 'TWO_FACTOR_INVALID')
      const session = issueSession(user)
      return {
        ...session,
        token_type: 'bearer',
        onboarding_state: deriveOnboardingState(user),
      } as T
    }

    case 'POST /auth/2fa/resend': {
      const req = body as unknown as { pending_token: string }
      const user = challengeUser(req.pending_token)
      // Only meaningful for a user already enrolled in email OTP; the contract
      // has nothing that switches factor mid-challenge (tdd.md §14.4).
      if (user.two_factor.method !== 'email_otp') fail(422, 'VALIDATION_ERROR')
      return { sent_to: maskEmail(user.email), expires_in: 300 } as T
    }

    case 'POST /auth/2fa/enroll': {
      const req = body as unknown as TwoFactorEnrollRequest
      const user = challengeUser(req.enrollment_token)
      user.two_factor.method = req.method
      if (req.method === 'totp') {
        return {
          method: 'totp',
          secret: 'JBSWY3DPEHPK3PXP',
          otpauth_uri: `otpauth://totp/EduBridge:${user.email}?secret=JBSWY3DPEHPK3PXP`,
          qr_svg: QR_SVG,
        } as T
      }
      return { method: 'email_otp', sent_to: maskEmail(user.email), expires_in: 600 } as T
    }

    case 'POST /auth/2fa/confirm': {
      const req = body as unknown as TwoFactorConfirmRequest
      const user = challengeUser(req.enrollment_token)
      if (req.code !== '123456') fail(401, 'TWO_FACTOR_INVALID')
      user.two_factor.status = 'active'
      user.backup_codes = Array.from(
        { length: 10 },
        (_, i) => `BKUP${String(i).padStart(4, '0')}`,
      )
      const session = issueSession(user)
      return {
        two_factor: { enabled: true, method: user.two_factor.method ?? 'totp' },
        backup_codes: user.backup_codes,
        onboarding_state: deriveOnboardingState(user),
        ...session,
      } as T
    }

    case 'POST /auth/email/verify': {
      const req = body as unknown as EmailVerifyRequest
      // Fixed shapes so every documented state can be driven from a URL:
      //   verify-<user id>  -> success        expired-token -> 410
      //   anything else     -> 400 INVALID_TOKEN
      if (req.token === 'expired-token') fail(410, 'TOKEN_EXPIRED')
      const user = users.find((u) => u.id === req.token.replace('verify-', ''))
      if (!user) fail(400, 'INVALID_TOKEN')
      user.email_verified_at = new Date().toISOString()
      const session = issueSession(user)
      return {
        email_verified: true,
        onboarding_state: deriveOnboardingState(user),
        enrollment_token: registerChallenge('enroll', user),
        ...session,
      } as T
    }

    case 'POST /auth/email/resend': {
      const req = body as unknown as EmailResendRequest
      void req
      return { sent: true } as T
    }

    case 'POST /auth/password/forgot':
      // Identical response whether or not the address exists.
      return { sent: true } as T

    case 'POST /auth/password/reset': {
      const req = body as unknown as { token: string; new_password: string }
      if (req.token === 'expired-token') fail(410, 'TOKEN_EXPIRED')
      if (!req.token.startsWith('reset-')) fail(400, 'INVALID_TOKEN')
      if (req.new_password.length < 8) {
        fail(400, 'VALIDATION_ERROR', {
          fields: { new_password: 'Use at least 8 characters.' },
        })
      }
      return { reset: true } as T
    }

    case 'POST /auth/guardian/invite': {
      const req = body as unknown as GuardianInviteRequest
      const user = userFor(init)
      if (req.parent_email.toLowerCase() === user.email.toLowerCase()) {
        fail(422, 'SELF_LINK_FORBIDDEN')
      }
      // The parent must already have an account (tdd.md §3.1 decision 2), so
      // the commonest outcome on this screen is 422 GUARDIAN_NOT_FOUND. The
      // mock has to model it or the gate screen's likeliest path is never
      // exercised in development. Any address ending `@parent.test` resolves;
      // everything else does not.
      if (
        !users.some(
          (u) =>
            u.role === 'parent' && u.email.toLowerCase() === req.parent_email.toLowerCase(),
        ) &&
        !req.parent_email.toLowerCase().endsWith('@parent.test')
      ) {
        fail(422, 'GUARDIAN_NOT_FOUND')
      }
      user.guardian.parent_email = req.parent_email
      user.guardian.status = 'pending'
      user.guardian.invited_at = new Date().toISOString()
      // The real invite token arrives by email. Here it is `invite-<student id>`,
      // so a developer can open the parent's side directly:
      //   /en/guardian/confirm?token=invite-u-s9
      return {
        invite_sent: true,
        parent_email: maskEmail(req.parent_email),
        status: 'pending',
      } as T
    }

    case 'POST /auth/guardian/confirm': {
      const req = body as unknown as { invite_token: string }
      const parent = userFor(init)
      if (parent.role !== 'parent') fail(403, 'FORBIDDEN_SCOPE')

      const student = users.find((u) => u.id === req.invite_token.replace('invite-', ''))
      if (!student) fail(400, 'INVALID_TOKEN')
      if (student.id === parent.id) fail(422, 'SELF_LINK_FORBIDDEN')
      if (student.guardian.status === 'verified') fail(409, 'GUARDIAN_ALREADY_LINKED')

      student.guardian.status = 'verified'
      return { status: 'verified', student_name: student.full_name } as T
    }

    case 'GET /auth/guardian/status': {
      const user = userFor(init)
      return {
        required: user.guardian.required,
        status: user.guardian.status,
        parent_email:
          user.guardian.parent_email === null ? null : maskEmail(user.guardian.parent_email),
        invited_at: user.guardian.invited_at,
      } as T
    }

    case 'GET /auth/me':
      return meOf(userFor(init)) as T

    case 'POST /auth/refresh': {
      if (currentAccessToken === null) fail(401, 'UNAUTHENTICATED')
      const id = sessions.get(currentAccessToken)
      const user = users.find((u) => u.id === id)
      if (!user) fail(401, 'UNAUTHENTICATED')
      return issueSession(user) as T
    }

    case 'POST /auth/logout':
      currentAccessToken = null
      return undefined as T

    case 'GET /subscription': {
      const user = userFor(init)
      const sub = user.subscription
      if (sub === null) fail(403, 'SUBSCRIPTION_REQUIRED')
      return {
        plan: PLAN,
        status: sub.status,
        trial_ends_at: sub.trial_ends_at,
        current_period_end: null,
      } as T
    }

    case 'POST /subscription/select': {
      const user = userFor(init)
      user.subscription = { status: 'active', trial_ends_at: null }
      return { status: 'active' } as T
    }

    default:
      throw new ApiError(404, 'UNKNOWN', `No mock handler for ${key}`)
  }
}

// ---------------------------------------------------------------------------
// Short-lived challenge credentials
// ---------------------------------------------------------------------------

const challenges = new Map<string, string>()

function registerChallenge(kind: 'pending' | 'enroll', user: MockUser): string {
  const token = nextToken(kind)
  challenges.set(token, user.id)
  return token
}

function challengeUser(token: string): MockUser {
  const id = challenges.get(token)
  if (id === undefined) fail(401, 'PENDING_TOKEN_EXPIRED')
  const user = users.find((u) => u.id === id)
  if (user === undefined) fail(401, 'PENDING_TOKEN_EXPIRED')
  return user
}

function validCodeFor(type: TwoFactorVerifyRequest['type']): string {
  return type === 'backup_code' ? 'BKUP0000' : '123456'
}
