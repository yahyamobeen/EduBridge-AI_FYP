import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { __resetTokenStoreForTests, getAccessToken } from '@/lib/auth/tokenStore'
import { __resetClientForTests, apiFetch, rememberSession } from './client'
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

// FINDING A11 — the four "onboarding redirects" tests are DELETED with the code
// they covered (owner's decision, 2026-08-16).
//
// ⚠️ THEY PASSED, AND THEY DESCRIBED BEHAVIOUR THE APPLICATION DID NOT HAVE.
//    Each one called `setNavigationHandler` itself, which is the only thing in
//    the entire repository that ever did — no provider registered a handler, so
//    in the running application `navigate` was permanently `null` and
//    `handleOnboardingRedirect` returned on its first line every time.
//
//    The tests were not wrong about the code; they were wrong about the world.
//    That is the more dangerous kind, because a green suite is exactly what
//    stops anyone from checking. `SessionGuard` re-evaluates `onboarding_state`
//    on every mount and is what actually moves a gated or lapsed user.

describe('files (classroom Phase 6)', () => {
  type Sent = { path: string; init: RequestInit }

  function capture(respondWith: (path: string, n: number) => Response) {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
      const path = url.replace(/^.*?(?=\/)/, '')
      sent.push({ path, init })
      return respondWith(path, sent.length)
    })
    return sent
  }

  function blobResponse(status: number, blob: Blob, errorBody: unknown = null): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      blob: async () => blob,
      json: async () => errorBody,
    } as Response
  }

  it('sends a raw body as it is, with the caller-supplied type and no JSON type', async () => {
    rememberSession('token', 900)
    const file = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    const sent = capture(() => respond(201, { id: 'f-1' }))
    await apiFetch('/assignments/a/submission/files', {
      method: 'POST',
      rawBody: file,
      headers: { 'Content-Type': 'application/pdf', 'X-Upload-Filename': 'lab.pdf' },
    })
    const headers = sent[0]!.init.headers as Record<string, string>
    expect(sent[0]!.init.body).toBe(file)
    expect(headers['Content-Type']).toBe('application/pdf')
    expect(headers.Authorization).toBe('Bearer token')
  })

  it('returns a successful download as a Blob', async () => {
    const file = new Blob(['bytes'])
    capture(() => blobResponse(200, file))
    await expect(apiFetch('/attachments/x/content', { responseType: 'blob' })).resolves.toBe(
      file,
    )
  })

  it('still turns a refused download into an ApiError', async () => {
    capture(() => blobResponse(403, new Blob(), envelope('FORBIDDEN_SCOPE')))
    const caught = await apiFetch('/attachments/x/content', { responseType: 'blob' }).catch(
      (e: unknown) => e,
    )
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).code).toBe('FORBIDDEN_SCOPE')
  })

  it('re-sends the same file after refreshing an expired session', async () => {
    rememberSession('stale', 900)
    const file = new Blob(['%PDF-1.7'])
    const sent = capture((path, n) =>
      path === '/auth/refresh'
        ? respond(200, { access_token: 'fresh', expires_in: 900 })
        : n === 1
          ? respond(401, envelope('UNAUTHENTICATED'))
          : respond(201, { id: 'f-1' }),
    )
    await apiFetch('/assignments/a/submission/files', { method: 'POST', rawBody: file })
    const uploads = sent.filter((s) => s.path !== '/auth/refresh')
    expect(uploads).toHaveLength(2)
    expect(uploads[1]!.init.body).toBe(file)
  })
})
