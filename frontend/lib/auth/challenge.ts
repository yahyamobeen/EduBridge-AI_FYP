import type { TwoFactorMethod } from '@/lib/api/types'

/**
 * Short-lived credentials handed between two screens of one flow.
 *
 * `pending_token` and `enrollment_token` are bearer credentials: presenting one
 * completes an authentication step. So they follow exactly the same storage
 * rule as the access token — a module variable and nowhere else. Never
 * localStorage, sessionStorage, a readable cookie, or a query string
 * (tdd.md §6.11).
 *
 * The consequence is deliberate and is part of the design, not a defect: a hard
 * reload on /login/2fa loses the challenge, and the screen sends the user back
 * to /login to sign in again. A token that survived a reload would also survive
 * the user walking away from a shared device, which is the case prd.md §3.1
 * warns about.
 */

export type PendingChallenge = {
  token: string
  /** The method the SERVER chose. The screen opens on this, not on a default. */
  method: TwoFactorMethod
  expiresAtMs: number
  /** Unmasked, for "we sent a code to…" and for a resend the server can act on. */
  email: string
}

export type EnrollmentHandoff = {
  token: string
  expiresAtMs: number
  email: string
}

let pending: PendingChallenge | null = null
let enrollment: EnrollmentHandoff | null = null

/**
 * The address the user typed, kept because
 * `status: 'email_verification_required'` returns a MASKED address. A masked
 * address cannot be submitted to /auth/email/resend, so the unmasked one the
 * user gave us is the only usable value (tdd.md §3.1).
 */
let unverifiedEmail: string | null = null

export function setPendingChallenge(challenge: PendingChallenge): void {
  pending = challenge
}

export function getPendingChallenge(): PendingChallenge | null {
  return pending
}

export function clearPendingChallenge(): void {
  pending = null
}

export function setEnrollmentHandoff(handoff: EnrollmentHandoff): void {
  enrollment = handoff
}

export function getEnrollmentHandoff(): EnrollmentHandoff | null {
  return enrollment
}

export function clearEnrollmentHandoff(): void {
  enrollment = null
}

export function setUnverifiedEmail(email: string): void {
  unverifiedEmail = email
}

export function getUnverifiedEmail(): string | null {
  return unverifiedEmail
}

/** Called once a session exists, so a spent challenge cannot be replayed. */
export function clearAllChallenges(): void {
  pending = null
  enrollment = null
  unverifiedEmail = null
}

/** Test-only reset so state does not leak between cases. */
export function __resetChallengesForTests(): void {
  clearAllChallenges()
}
