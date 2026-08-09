/**
 * The error envelope from tdd.md §7.3:
 *   { "error": { "code": "...", "message": "...", "details": {} } }
 *
 * Clients branch on `code`, NEVER on `message` -- messages are localized and
 * will change. An unrecognised code must still render a usable state.
 */

export const ERROR_CODES = [
  'VALIDATION_ERROR',
  'INVALID_TOKEN',
  'TOKEN_EXPIRED',
  'UNAUTHENTICATED',
  'TWO_FACTOR_INVALID',
  'PENDING_TOKEN_EXPIRED',
  'TWO_FACTOR_LOCKED',
  'GATE_PENDING',
  'SUBSCRIPTION_REQUIRED',
  'FORBIDDEN_SCOPE',
  'EMAIL_ALREADY_REGISTERED',
  'GUARDIAN_ALREADY_LINKED',
  // 422 from `POST /auth/guardian/invite`: no ACTIVE PARENT account uses that
  // address. The likeliest outcome of the gate screen, not an edge case — the
  // parent has to sign up before the student can invite them (tdd.md §3.1
  // decision 2) — so it needs its own message, never the generic one.
  'GUARDIAN_NOT_FOUND',
  'ATTEMPT_EXISTS',
  'INVALID_CLASS_GROUP',
  // Turnstile token rejected by Cloudflare siteverify. 400, but NOT
  // VALIDATION_ERROR: the client must reset the widget and re-solve, because
  // the token is single-use and may be consumed by the failed POST.
  'CAPTCHA_FAILED',
  'SELF_LINK_FORBIDDEN',
  'NOT_GROUNDED',
  'RATE_LIMITED',
  'MODEL_UNAVAILABLE',
] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

export type ErrorDetails = {
  /** Per-field messages for VALIDATION_ERROR. */
  fields?: Record<string, string>
  /** ISO timestamp for TWO_FACTOR_LOCKED. */
  locked_until?: string
  /** Seconds, for RATE_LIMITED, mirroring the Retry-After header. */
  retry_after?: number
  [key: string]: unknown
}

export type ErrorEnvelope = {
  error: { code: string; message: string; details?: ErrorDetails }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorCode | string
  readonly details: ErrorDetails

  constructor(status: number, code: string, message: string, details: ErrorDetails = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** True only for codes we have a designed UI state for. */
  isKnown(): this is ApiError & { code: ErrorCode } {
    return (ERROR_CODES as readonly string[]).includes(this.code)
  }

  fieldErrors(): Record<string, string> {
    return this.details.fields ?? {}
  }
}

/** Builds an ApiError from a response body, tolerating a malformed envelope. */
export function toApiError(status: number, body: unknown): ApiError {
  const envelope = body as Partial<ErrorEnvelope> | null
  const error = envelope?.error
  if (error && typeof error.code === 'string') {
    return new ApiError(status, error.code, error.message ?? error.code, error.details ?? {})
  }
  // A proxy, a gateway or a crash can return HTML or an empty body. Callers
  // still get an ApiError so no screen has to special-case "no envelope".
  return new ApiError(status, 'UNKNOWN', `Request failed with status ${status}`)
}

/**
 * Which 401s mean "the access token expired" and are worth a silent refresh.
 *
 * TWO_FACTOR_INVALID and PENDING_TOKEN_EXPIRED are also 401s, but they mean the
 * submitted code was wrong or its challenge died. Refreshing and retrying those
 * would resubmit a bad code and burn one of the user's lockout attempts, so
 * this is an allow-list rather than a status check (tdd.md §3.10).
 */
const REFRESHABLE_401_CODES = new Set<string>(['UNAUTHENTICATED', 'UNKNOWN'])

export function isRefreshableAuthError(error: ApiError): boolean {
  return error.status === 401 && REFRESHABLE_401_CODES.has(error.code)
}
