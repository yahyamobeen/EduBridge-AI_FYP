/**
 * The access token lives in a module-level variable and nowhere else.
 *
 * Never localStorage, sessionStorage, a readable cookie, or a URL: any of those
 * survive the tab and are readable by injected script. The refresh token is an
 * httpOnly cookie the server sets, which JavaScript cannot read at all
 * (tdd.md §3.10, §6.11).
 *
 * A consequence worth knowing: a full page reload loses the access token, and
 * the app recovers by calling /auth/refresh with the cookie. That is the
 * intended trade-off, not a bug.
 */

let accessToken: string | null = null
let expiresAtMs: number | null = null

/** Refresh once the token is this far through its life, rather than on failure. */
const REFRESH_AT_FRACTION = 0.8

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string, expiresInSeconds: number): void {
  accessToken = token
  expiresAtMs = Date.now() + expiresInSeconds * 1000
}

export function clearAccessToken(): void {
  accessToken = null
  expiresAtMs = null
}

export function hasAccessToken(): boolean {
  return accessToken !== null
}

/**
 * True once the token is far enough through its lifetime to refresh ahead of
 * use. Waiting for a 401 instead would interrupt a student mid-form.
 *
 * `lifetimeSeconds` is the original `expires_in`, needed because only the
 * absolute expiry is stored.
 */
export function shouldRefreshAhead(lifetimeSeconds: number, now = Date.now()): boolean {
  if (accessToken === null || expiresAtMs === null) return false
  const issuedAtMs = expiresAtMs - lifetimeSeconds * 1000
  const elapsed = now - issuedAtMs
  return elapsed >= lifetimeSeconds * 1000 * REFRESH_AT_FRACTION
}

/** True when the token is already past its expiry. */
export function isExpired(now = Date.now()): boolean {
  return expiresAtMs !== null && now >= expiresAtMs
}

/** Test-only reset so state does not leak between cases. */
export function __resetTokenStoreForTests(): void {
  accessToken = null
  expiresAtMs = null
}
