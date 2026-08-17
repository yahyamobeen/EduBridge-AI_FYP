import {
  clearAccessToken,
  getAccessToken,
  isExpired,
  setAccessToken,
  shouldRefreshAhead,
} from '@/lib/auth/tokenStore'
import { ApiError, isRefreshableAuthError, toApiError } from './errors'
import type { RefreshResponse } from './types'

/**
 * THE EMPTY STRING IS LOAD-BEARING IN THE BROWSER. Do not "fix" it.
 *
 * A relative `/api/...` path goes through the rewrite in next.config.mjs, and
 * that rewrite is what keeps the refresh cookie same-site. Pointing this at the
 * backend's public address re-breaks it silently, in production only, roughly
 * fifteen minutes after each login (see frontend/CLAUDE.md).
 *
 * On the SERVER there is no origin to be relative to, and Node cannot parse a
 * relative URL — so a server component fetching without a configured base URL
 * fails three frames deep in `fetch`. The mock layer used to hide that by
 * defaulting on outside production; with the mocks gone, it is named instead.
 */
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''

function resolve(path: string): string {
  if (BASE_URL) return `${BASE_URL}${path}`
  if (typeof window === 'undefined') {
    throw new Error(
      'NEXT_PUBLIC_API_BASE_URL is not set, and a relative API path cannot be ' +
        'resolved on the server. Set it in .env.local (see .env.example) and ' +
        'restart the dev server — NEXT_PUBLIC_* values are inlined at build time.',
    )
  }
  return path
}

/** Access-token lifetime from the last issue, needed for proactive refresh. */
let lastLifetimeSeconds = 0

export function rememberSession(token: string, expiresInSeconds: number): void {
  lastLifetimeSeconds = expiresInSeconds
  setAccessToken(token, expiresInSeconds)
}

export function endSession(): void {
  lastLifetimeSeconds = 0
  clearAccessToken()
}

// ---------------------------------------------------------------------------
// FINDING A11 — the navigation handoff is DELETED (owner's decision, 2026-08-16)
//
// There was a `setNavigationHandler` seam here, plus `handleOnboardingRedirect`
// on the 403 path, so the client could send a user to an onboarding step without
// importing the router. It was well built and it NEVER RAN: the only caller of
// `setNavigationHandler` in the entire repository was `client.test.ts`. No
// provider ever registered a handler, so `navigate` was permanently `null` and
// the redirect returned on its first line every single time.
//
// ⚠️ DELETED RATHER THAN WIRED UP, and the reason is not that wiring it is hard.
//    `SessionGuard` re-evaluates `onboarding_state` on every mount and catches
//    the same two conditions, so nobody is ever stranded. What the seam would
//    have added is catching a mid-session trial lapse BEFORE the next
//    navigation — real, but small.
//
//    What it cost was worse: four passing tests describing behaviour the
//    application does not have. A tested-but-dead path is how the next reader
//    concludes the feature works, and it is how a reviewer concludes the 403
//    redirect is covered.
//
// If the mid-session case is wanted later, the honest form is a React-side
// interceptor that owns the router directly — not a global seam whose
// registration can be forgotten silently.
// ---------------------------------------------------------------------------

export function __resetClientForTests(): void {
  lastLifetimeSeconds = 0
  refreshInFlight = null
}

// ---------------------------------------------------------------------------
// Refresh
// ---------------------------------------------------------------------------

let refreshInFlight: Promise<boolean> | null = null

/**
 * Single-flight: N concurrent 401s must trigger ONE refresh, not N. Without
 * this a dashboard firing several requests at once would send a burst of
 * refreshes, and with rotation enabled all but one would be rejected.
 */
export function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

async function performRefresh(): Promise<boolean> {
  try {
    // Deliberately bypasses apiFetch: a refresh that 401s must not recurse
    // back into the retry path.
    const body = await rawRequest<RefreshResponse>('/auth/refresh', { method: 'POST' })
    rememberSession(body.access_token, body.expires_in)
    return true
  } catch {
    endSession()
    return false
  }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

export type ApiRequestInit = {
  method?: string
  body?: unknown
  /** Sent instead of the session token, for short-lived challenge credentials. */
  bearer?: string
  /**
   * Opts out of refresh-and-retry on a 401.
   *
   * For most endpoints a 401 UNAUTHENTICATED means the access token died and a
   * refresh is worth trying — that is how the app recovers after a reload, when
   * only the httpOnly cookie survives. On /auth/login it means the password was
   * wrong, so refreshing would fire a guaranteed-to-fail request on every typo.
   */
  noRetry?: boolean
  headers?: Record<string, string>
  signal?: AbortSignal
}

async function rawRequest<T>(path: string, init: ApiRequestInit): Promise<T> {
  const token = init.bearer ?? getAccessToken()
  const response = await fetch(resolve(path), {
    method: init.method ?? 'GET',
    // Carries the httpOnly refresh cookie.
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
    ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
    ...(init.signal ? { signal: init.signal } : {}),
  })

  if (response.status === 204) return undefined as T

  const payload = await response.json().catch(() => null)
  if (!response.ok) throw toApiError(response.status, payload)
  return payload as T
}

/**
 * The single entry point for every call. Handles proactive refresh, one
 * retry after a genuine session expiry, and the onboarding redirects.
 */
export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  // Refresh ahead of use rather than waiting to be told, so a long form is not
  // interrupted by a redirect the user did not cause.
  if (init.bearer === undefined && getAccessToken() !== null) {
    if (isExpired() || shouldRefreshAhead(lastLifetimeSeconds)) {
      await refreshOnce()
    }
  }

  try {
    return await rawRequest<T>(path, init)
  } catch (error) {
    if (!(error instanceof ApiError)) throw error

    // A short-lived challenge credential is not a session; refreshing cannot
    // help it, and retrying would waste an attempt.
    if (init.bearer === undefined && !init.noRetry && isRefreshableAuthError(error)) {
      if (await refreshOnce()) return rawRequest<T>(path, init)
    }

    // A11: `handleOnboardingRedirect(error)` stood here and did nothing —
    // `navigate` was never registered. `SessionGuard` handles GATE_PENDING and
    // SUBSCRIPTION_REQUIRED on mount, which is what actually runs.
    throw error
  }
}
