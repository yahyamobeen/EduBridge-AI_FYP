import { apiFetch, endSession, rememberSession } from './client'
import type {
  EmailResendRequest,
  EmailVerifyRequest,
  EmailVerifyResponse,
  EnumsResponse,
  GuardianConfirmRequest,
  GuardianConfirmResponse,
  GuardianInviteRequest,
  GuardianInviteResponse,
  GuardianStatusResponse,
  LoginRequest,
  LoginResponse,
  MeResponse,
  MeUpdateRequest,
  PasswordChangeRequest,
  PasswordForgotRequest,
  PasswordResetRequest,
  RegisterRequest,
  RegisterResponse,
  TwoFactorConfirmRequest,
  TwoFactorConfirmResponse,
  TwoFactorEnrollRequest,
  TwoFactorEnrollResponse,
  TwoFactorResendRequest,
  TwoFactorResendResponse,
  TwoFactorStatusResponse,
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
 * Segregated administrator sign-in (prd.md FR-A2a).
 *
 * SAME REQUEST, SAME RESPONSE, SAME BRANCHING RULE as `login` above — only the
 * path differs, because the SERVER decides which roles may authenticate where.
 * An administrator submitting the public form and an ordinary user submitting
 * this one both get a 401 whose body is byte-identical to a wrong password, so
 * neither endpoint can be used to discover which addresses are administrators.
 *
 * ⚠️ The unlisted URL the form is reached at is NOT the control; this endpoint
 *    is. Do not add a role check in the browser and consider anything protected.
 */
export function adminLogin(body: LoginRequest): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/auth/admin/login', { method: 'POST', body, noRetry: true })
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

/**
 * Re-sends the OTP for a challenge whose enrolled method is ALREADY email OTP.
 *
 * It cannot start an email-OTP challenge for a TOTP-enrolled user — there is no
 * endpoint for that, which is why the challenge screen offers a backup code
 * rather than a factor switch (tdd.md §14.4 finding 1).
 */
export function twoFactorResend(
  body: TwoFactorResendRequest,
): Promise<TwoFactorResendResponse> {
  return apiFetch<TwoFactorResendResponse>('/auth/2fa/resend', { method: 'POST', body })
}

// ---------------------------------------------------------------------------
// Two-factor enrolment
// ---------------------------------------------------------------------------

/**
 * Starts enrolment in the chosen method. `enrollment_token` travels in the body
 * (decision 6), so this is not an authenticated call in the usual sense — the
 * user has no session yet.
 *
 * Calling it a second time with the same method is also how an email OTP is
 * re-sent, because `2fa/resend` takes a pending token rather than an enrollment
 * token (tdd.md §14.4 finding 2).
 */
export function twoFactorEnroll(
  body: TwoFactorEnrollRequest,
): Promise<TwoFactorEnrollResponse> {
  return apiFetch<TwoFactorEnrollResponse>('/auth/2fa/enroll', { method: 'POST', body })
}

/** Confirms the first code. Returns the backup codes ONCE, plus a session. */
export function twoFactorConfirm(
  body: TwoFactorConfirmRequest,
): Promise<TwoFactorConfirmResponse> {
  return apiFetch<TwoFactorConfirmResponse>('/auth/2fa/confirm', { method: 'POST', body })
}

// ---------------------------------------------------------------------------
// Email verification and password reset
// ---------------------------------------------------------------------------

/**
 * The returned `access_token` is scoped to onboarding routes only. If it ever
 * reached protected resources, verifying an email address alone would be a full
 * login and 2FA would be bypassable (tdd.md §3.1, contract delta 1).
 */
export function verifyEmail(body: EmailVerifyRequest): Promise<EmailVerifyResponse> {
  return apiFetch<EmailVerifyResponse>('/auth/email/verify', { method: 'POST', body })
}

export function resendVerification(body: EmailResendRequest): Promise<void> {
  return apiFetch<void>('/auth/email/resend', { method: 'POST', body })
}

/**
 * The response is identical whether or not the address exists (tdd.md §3.1), so
 * the screen must show the same confirmation either way. Branching on it would
 * turn this form into an account-enumeration oracle.
 */
export function forgotPassword(body: PasswordForgotRequest): Promise<void> {
  return apiFetch<void>('/auth/password/forgot', { method: 'POST', body })
}

export function resetPassword(body: PasswordResetRequest): Promise<void> {
  return apiFetch<void>('/auth/password/reset', { method: 'POST', body })
}

// ---------------------------------------------------------------------------
// Guardian gate
// ---------------------------------------------------------------------------

export function guardianInvite(body: GuardianInviteRequest): Promise<GuardianInviteResponse> {
  return apiFetch<GuardianInviteResponse>('/auth/guardian/invite', { method: 'POST', body })
}

export function guardianStatus(signal?: AbortSignal): Promise<GuardianStatusResponse> {
  return apiFetch<GuardianStatusResponse>('/auth/guardian/status', signal ? { signal } : {})
}

/** Authenticated as the PARENT (v0.3.2) — the student cannot call this. */
export function guardianConfirm(
  body: GuardianConfirmRequest,
): Promise<GuardianConfirmResponse> {
  return apiFetch<GuardianConfirmResponse>('/auth/guardian/confirm', { method: 'POST', body })
}

export function getMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>('/auth/me')
}

// ---------------------------------------------------------------------------
// FR-A8 — manage own account. The settings screen is the only caller.
// ---------------------------------------------------------------------------

/**
 * Returns the WHOLE `MeResponse`, not a patch result, so a caller can replace
 * its cached user outright instead of merging two shapes.
 */
export function updateMe(body: MeUpdateRequest): Promise<MeResponse> {
  return apiFetch<MeResponse>('/auth/me', { method: 'PATCH', body })
}

/**
 * ⚠️ `noRetry` IS LOAD-BEARING HERE, AND THIS IS THE ONLY ROUTE WHERE IT IS
 *    SUBTLE.
 *
 * A wrong CURRENT password returns `401 UNAUTHENTICATED` — the contract makes
 * that "also the only response meaning 'wrong password'" (tdd.md:1053) and
 * forbids inventing a code (tdd.md:1074). `UNAUTHENTICATED` is also in
 * `REFRESHABLE_401_CODES` (errors.ts), because it normally means an expired
 * access token. So this is the one endpoint where BOTH meanings of that 401 are
 * live at once, and without `noRetry` every mistyped password would silently
 * fire a token refresh and replay the request.
 *
 * The `init.bearer === undefined` guard in client.ts does NOT cover this: unlike
 * `/2fa/confirm`, the credential here is not passed as `bearer`.
 *
 * Resolves with nothing (204). ⚠️ EVERY REFRESH TOKEN IS REVOKED, INCLUDING THE
 * CALLER'S OWN — the next refresh will fail by design, and the caller should
 * treat that as "sign in again" rather than as an error.
 */
export function changePassword(body: PasswordChangeRequest): Promise<void> {
  return apiFetch<void>('/auth/password/change', { method: 'POST', body, noRetry: true })
}

/** Own second factor. Never returns the secret. */
export function twoFactorStatus(): Promise<TwoFactorStatusResponse> {
  return apiFetch<TwoFactorStatusResponse>('/auth/2fa/status')
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
