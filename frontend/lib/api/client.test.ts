import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { __resetTokenStoreForTests, getAccessToken } from '@/lib/auth/tokenStore'
import {
  __resetClientForTests,
  apiFetch,
  rememberSession,
  setNavigationHandler,
} from './client'
import { ApiError } from './errors'

type Handler = (path: string) => { status: number; body: unknown }

let handler: Handler
let calls: string[]

function envelope(code: string) {
  return { error: { code, message: code } }
}

function respond(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

beforeEach(() => {
  __resetTokenStoreForTests()
  __resetClientForTests()
  calls = []
  vi.stubGlobal('fetch', async (url: string) => {
    const path = url.replace(/^.*?(?=\/)/, '')
    calls.push(path)
    const { status, body } = handler(path)
    return respond(status, body)
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('successful requests', () => {
  it('sends the access token and returns the parsed body', async () => {
    rememberSession('tok', 900)
    handler = () => ({ status: 200, body: { ok: true } })
    await expect(apiFetch('/auth/me')).resolves.toEqual({ ok: true })
  })

  it('returns undefined for a 204 rather than trying to parse a body', async () => {
    handler = () => ({ status: 204, body: null })
    await expect(apiFetch('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
  })
})

describe('refresh on expiry', () => {
  it('refreshes once and retries the original request', async () => {
    rememberSession('stale', 900)
    let protectedCalls = 0
    handler = (path) => {
      if (path === '/auth/refresh') {
        return { status: 200, body: { access_token: 'fresh', expires_in: 900 } }
      }
      protectedCalls += 1
      return protectedCalls === 1
        ? { status: 401, body: envelope('UNAUTHENTICATED') }
        : { status: 200, body: { ok: true } }
    }

    await expect(apiFetch('/auth/me')).resolves.toEqual({ ok: true })
    expect(getAccessToken()).toBe('fresh')
    expect(calls.filter((c) => c === '/auth/refresh')).toHaveLength(1)
  })

  it('fires ONE refresh for several concurrent 401s, not one each', async () => {
    // With rotation enabled a burst of refreshes would see all but one
    // rejected, signing the user out mid-session.
    rememberSession('stale', 900)
    const seen = new Map<string, number>()
    handler = (path) => {
      if (path === '/auth/refresh') {
        return { status: 200, body: { access_token: 'fresh', expires_in: 900 } }
      }
      const n = (seen.get(path) ?? 0) + 1
      seen.set(path, n)
      return n === 1
        ? { status: 401, body: envelope('UNAUTHENTICATED') }
        : { status: 200, body: { ok: path } }
    }

    await Promise.all([apiFetch('/a'), apiFetch('/b'), apiFetch('/c')])
    expect(calls.filter((c) => c === '/auth/refresh')).toHaveLength(1)
  })

  it('gives up after a single retry rather than looping', async () => {
    rememberSession('stale', 900)
    handler = (path) =>
      path === '/auth/refresh'
        ? { status: 200, body: { access_token: 'fresh', expires_in: 900 } }
        : { status: 401, body: envelope('UNAUTHENTICATED') }

    await expect(apiFetch('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(calls.filter((c) => c === '/auth/me')).toHaveLength(2)
  })

  it('clears the session when the refresh itself fails', async () => {
    rememberSession('stale', 900)
    handler = () => ({ status: 401, body: envelope('UNAUTHENTICATED') })
    await expect(apiFetch('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(getAccessToken()).toBeNull()
  })

  it('does NOT refresh or retry a wrong two-factor code', async () => {
    // Retrying would resubmit the bad code and burn a lockout attempt.
    rememberSession('tok', 900)
    handler = () => ({ status: 401, body: envelope('TWO_FACTOR_INVALID') })

    await expect(apiFetch('/auth/2fa/verify', { method: 'POST' })).rejects.toMatchObject({
      code: 'TWO_FACTOR_INVALID',
    })
    expect(calls.filter((c) => c === '/auth/refresh')).toHaveLength(0)
    expect(calls.filter((c) => c === '/auth/2fa/verify')).toHaveLength(1)
  })

  it('does not attempt a refresh for a challenge-token request', async () => {
    handler = () => ({ status: 401, body: envelope('UNAUTHENTICATED') })
    await expect(
      apiFetch('/auth/2fa/enroll', { method: 'POST', bearer: 'enroll-1' }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(calls.filter((c) => c === '/auth/refresh')).toHaveLength(0)
  })
})

describe('onboarding redirects', () => {
  it('sends a gated student to the guardian step instead of showing an error', async () => {
    const navigate = vi.fn()
    setNavigationHandler(navigate, () => '/en/dashboard')
    rememberSession('tok', 900)
    handler = () => ({ status: 403, body: envelope('GATE_PENDING') })

    await expect(apiFetch('/tutor/ask', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
    expect(navigate).toHaveBeenCalledWith('/onboarding/guardian')
  })

  it('sends a lapsed trial to plan selection', async () => {
    const navigate = vi.fn()
    setNavigationHandler(navigate, () => '/en/dashboard')
    rememberSession('tok', 900)
    handler = () => ({ status: 403, body: envelope('SUBSCRIPTION_REQUIRED') })

    await expect(apiFetch('/tutor/ask', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
    expect(navigate).toHaveBeenCalledWith('/onboarding/plan')
  })

  it('does not redirect to the page it is already on', async () => {
    // The gate page calls guardian endpoints; redirecting there would loop.
    const navigate = vi.fn()
    setNavigationHandler(navigate, () => '/en/onboarding/guardian')
    rememberSession('tok', 900)
    handler = () => ({ status: 403, body: envelope('GATE_PENDING') })

    await expect(apiFetch('/auth/guardian/status')).rejects.toBeInstanceOf(ApiError)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('leaves other 403s to the screen to render', async () => {
    const navigate = vi.fn()
    setNavigationHandler(navigate, () => '/en/teacher')
    rememberSession('tok', 900)
    handler = () => ({ status: 403, body: envelope('FORBIDDEN_SCOPE') })

    await expect(apiFetch('/reports/weekly')).rejects.toMatchObject({ code: 'FORBIDDEN_SCOPE' })
    expect(navigate).not.toHaveBeenCalled()
  })
})
