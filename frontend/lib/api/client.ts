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
 * Mock mode is the DEFAULT outside production.
 *
 * The backend does not exist yet, so a developer who has not copied
 * .env.example to .env.local would otherwise get a real fetch against an empty
 * base URL — which on the server is a relative path Node cannot parse, so every
 * page that loads data fails with an unhelpful error. Defaulting to mocks in
 * development means the app runs on checkout; production still requires the
 * flag to be set explicitly, so mocks can never be shipped by omission.
 */
const API_MODE = process.env.NEXT_PUBLIC_API_MODE
const USE_MOCKS =
  API_MODE === 'mock' || (API_MODE === undefined && process.env.NODE_ENV !== 'production')

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''

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
// Navigation handoff
//
// The client must be able to send a user to an onboarding step on 403, but it
// must not import the router: that would make it untestable outside React and
// couple the transport to the framework. The provider registers a handler.
// ---------------------------------------------------------------------------

type NavigateFn = (path: string) => void

let navigate: NavigateFn | null = null
let currentPath: () => string = () => ''

export function setNavigationHandler(fn: NavigateFn, pathReader: () => string): void {
  navigate = fn
  currentPath = pathReader
}

export function __resetClientForTests(): void {
  navigate = null
  currentPath = () => ''
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
  if (USE_MOCKS) {
    // Dynamic so the mock handlers and their seeded users are not bundled into
    // a live build -- NEXT_PUBLIC_API_MODE is inlined, so this branch is
    // eliminated entirely when it is not 'mock'.
    const { mockRequest } = await import('./mock')
    return mockRequest<T>(path, init)
  }

  const token = init.bearer ?? getAccessToken()
  const response = await fetch(`${BASE_URL}${path}`, {
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

    handleOnboardingRedirect(error)
    throw error
  }
}

/**
 * `GATE_PENDING` and `SUBSCRIPTION_REQUIRED` both mean "authenticated, but an
 * onboarding precondition is unmet". Neither is an error to show; both are a
 * signal to move the user to the step that clears them.
 */
function handleOnboardingRedirect(error: ApiError): void {
  if (error.status !== 403 || navigate === null) return

  const target =
    error.code === 'GATE_PENDING'
      ? '/onboarding/guardian'
      : error.code === 'SUBSCRIPTION_REQUIRED'
        ? '/onboarding/plan'
        : null

  if (target === null) return
  // The gate page itself calls guardian endpoints. Redirecting to a page we
  // are already on would loop.
  if (currentPath().endsWith(target)) return

  navigate(target)
}
