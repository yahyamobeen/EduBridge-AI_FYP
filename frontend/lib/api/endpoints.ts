import { apiFetch, endSession, rememberSession } from './client'
import type {
  EnumsResponse,
  LoginRequest,
  LoginResponse,
  MeResponse,
  RegisterRequest,
  RegisterResponse,
  TwoFactorVerifyRequest,
  TwoFactorVerifyResponse,
} from './types'

/**
 * Typed wrappers so screens never hand-write a path or a shape.
 *
 * NOTE ON SERVER USAGE: only unauthenticated calls may run on the server. The
 * access token lives in module state (tdd.md §3.10), which on the server is
 * shared across requests and would leak between users. `getEnums` is safe
 * because the endpoint takes no auth; everything else here is client-only.
 */

export function getEnums(signal?: AbortSignal): Promise<EnumsResponse> {
  return apiFetch<EnumsResponse>('/reference/enums', signal ? { signal } : {})
}

/**
 * Registration deliberately returns no session: the account starts at
 * `email_verification_pending` and a token is only issued once the address is
 * confirmed (tdd.md §3.1).
 */
export function register(body: RegisterRequest): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>('/auth/register', { method: 'POST', body })
}

/**
 * A 200 from this endpoint is NEVER a credential failure.
 *
 * It means the password was right and the journey is simply incomplete, so the
 * caller must branch on `status` and move the user forward. Only a 401 means
 * the credentials were wrong (tdd.md §3.1). Treating a 200 as an error state --
 * the shape most login forms assume -- would strand every unverified or
 * un-enrolled user on this screen with no way out.
 */
export function login(body: LoginRequest): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/auth/login', { method: 'POST', body, noRetry: true })
}

/**
 * `pending_token` travels in the BODY, not as a bearer header (tdd.md §3.1).
 *
 * That also keeps it off the `bearer` path in the client, which exists for
 * credentials that must not trigger a refresh-and-retry. A wrong code returns
 * 401 TWO_FACTOR_INVALID, which the refresh allow-list deliberately excludes:
 * retrying it would resubmit the same wrong code and burn a lockout attempt.
 */
export function twoFactorVerify(
  body: TwoFactorVerifyRequest,
): Promise<TwoFactorVerifyResponse> {
  return apiFetch<TwoFactorVerifyResponse>('/auth/2fa/verify', { method: 'POST', body })
}

export function getMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>('/auth/me')
}

/**
 * Stores the issued session. Kept here rather than in each screen so there is
 * one place where a token enters the app, and so no screen has to remember that
 * `expires_in` is what drives proactive refresh.
 */
export function startSession(token: string, expiresInSeconds: number): void {
  rememberSession(token, expiresInSeconds)
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>('/auth/logout', { method: 'POST' })
  } finally {
    // The local session is dropped even if the server call fails: leaving a
    // usable token in memory after the user asked to sign out is the worse
    // outcome, especially on the shared devices prd.md §3.1 describes.
    endSession()
  }
}
