/**
 * How an API path becomes a URL, on the server and in the browser.
 *
 * ⚠️ THIS EXISTS BECAUSE THE STUDENT SIGNUP FORM WAS UNREACHABLE IN PRODUCTION
 *    WHILE EVERY TEST AND EVERY LOCAL RUN WAS GREEN.
 *
 * `app/[locale]/(site)/signup/student/page.tsx` is the only SERVER component
 * that calls the API — it fetches the board and class options so the academic
 * step has them on first paint. In production `NEXT_PUBLIC_API_BASE_URL` is the
 * relative `/api`, and it must be: that is what routes the browser through the
 * rewrite and keeps the refresh cookie same-site. But Node has no origin to
 * resolve a relative URL against, so `fetch('/api/reference/enums')` threw
 * `TypeError: Failed to parse URL` — and the page catches its own enum load and
 * degrades, so the real error surfaced nowhere at all.
 *
 * It could not reproduce locally: development sets an ABSOLUTE
 * `http://localhost:8000/api`, so the failing branch never ran. The symptom was
 * that student signup showed "Could not load the class and subject options"
 * while teacher and parent signup — neither of which fetches on the server —
 * worked perfectly.
 *
 * These cases are the four combinations that matter. The browser-relative one
 * is a SECURITY regression guard, not a formatting check: see its comment.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

const BACKEND = 'https://edubridge-backend-hntl.onrender.com'

/**
 * Re-import `client` with a fresh module registry, because `BASE_URL` and
 * `SERVER_ORIGIN` are module-scope constants read once at import — exactly as
 * Next inlines them at build time.
 */
async function load({
  base,
  origin,
  server,
}: {
  base?: string
  origin?: string
  server: boolean
}) {
  vi.resetModules()
  if (base === undefined) vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '')
  else vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', base)
  if (origin === undefined) vi.stubEnv('BACKEND_INTERNAL_URL', '')
  else vi.stubEnv('BACKEND_INTERNAL_URL', origin)

  // jsdom always defines `window`; the server is the absence of it.
  if (server) vi.stubGlobal('window', undefined)

  const mod = await import('./client')
  const seen: string[] = []
  vi.stubGlobal('fetch', async (url: string) => {
    seen.push(url)
    return { ok: true, status: 200, json: async () => ({}) } as Response
  })
  return { apiFetch: mod.apiFetch, seen }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('on the server', () => {
  it('resolves a relative base against BACKEND_INTERNAL_URL', async () => {
    const { apiFetch, seen } = await load({ base: '/api', origin: BACKEND, server: true })

    await apiFetch('/reference/enums')

    expect(seen[0]).toBe(`${BACKEND}/api/reference/enums`)
  })

  it('leaves an absolute base alone', async () => {
    // The development shape. It already works and must not be double-prefixed.
    const { apiFetch, seen } = await load({
      base: 'http://localhost:8000/api',
      origin: BACKEND,
      server: true,
    })

    await apiFetch('/reference/enums')

    expect(seen[0]).toBe('http://localhost:8000/api/reference/enums')
  })

  it('tolerates a trailing slash on the origin', async () => {
    const { apiFetch, seen } = await load({ base: '/api', origin: `${BACKEND}/`, server: true })

    await apiFetch('/reference/enums')

    expect(seen[0]).toBe(`${BACKEND}/api/reference/enums`)
  })

  it('names the missing variable instead of failing inside fetch', async () => {
    const { apiFetch } = await load({ base: '/api', origin: undefined, server: true })

    await expect(apiFetch('/reference/enums')).rejects.toThrow(
      /BACKEND_INTERNAL_URL is not set/,
    )
  })

  it('rejects a doubled scheme rather than building an unfetchable URL', async () => {
    // The exact value that was live on Render, and which also broke the rewrite
    // in next.config.mjs. It passes a naive "starts with https://" check.
    const { apiFetch } = await load({
      base: '/api',
      origin: `https://${BACKEND}`,
      server: true,
    })

    await expect(apiFetch('/reference/enums')).rejects.toThrow(/absolute http\(s\) URL/)
  })
})

describe('in the browser', () => {
  it('keeps a relative base relative', async () => {
    /**
     * ⚠️ SECURITY REGRESSION GUARD, NOT A FORMATTING TEST.
     *
     * The browser must call the SAME ORIGIN so the request goes through the
     * rewrite in `next.config.mjs`. `onrender.com` is on the Public Suffix
     * List, so the frontend and backend hosts are different SITES: pointed at
     * the backend directly, the `SameSite=Lax` refresh cookie is never sent and
     * every user is silently signed out about fifteen minutes after logging in,
     * in production only.
     *
     * So the server-side fix above must not leak into the browser path.
     */
    const { apiFetch, seen } = await load({ base: '/api', origin: BACKEND, server: false })

    await apiFetch('/reference/enums')

    expect(seen[0]).toBe('/api/reference/enums')
    expect(seen[0]).not.toContain(BACKEND)
  })
})
