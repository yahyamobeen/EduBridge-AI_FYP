/**
 * `proxy.ts` routes EVERY page on this site, so this file is the regression
 * guard for it. Before §1.6 it was four lines wrapping next-intl; it now has to
 * hide the administrator login behind a server-only secret WITHOUT disturbing
 * locale routing for anything else.
 *
 * The third branch — "everything else still reaches next-intl" — is the one
 * worth having. A secret path that stops working is a nuisance; a middleware
 * that stops calling next-intl takes down all 20 pages at once.
 *
 * ⚠️ `ADMIN_LOGIN_PATH` is read at MODULE SCOPE, because in production it is a
 *    deployment constant. Every test therefore sets the variable and then
 *    `vi.resetModules()` + dynamic `import()`, rather than importing once at the
 *    top. Importing at the top would freeze whichever value happened to be set
 *    first and quietly make the other cases assert nothing.
 */

import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

const SECRET = 'sdkjcdjk2-scdscdv-34jkdjkcn'

/**
 * A REAL `NextRequest`, not a hand-rolled `{ nextUrl }` object.
 *
 * The first version of this file used a stub, and next-intl's middleware read
 * `request.headers` and `request.cookies` off it and threw. A stub thin enough
 * to satisfy our own three branches would have made the "everything else still
 * reaches next-intl" tests assert nothing at all — which are the tests that
 * matter most here.
 */
function request(pathname: string) {
  return new NextRequest(`https://edubridge.example${pathname}`)
}

/**
 * Where a response was rewritten to, or `''` for "not rewritten at all".
 *
 * Collapsing the absent header to a string rather than leaving it `null` is
 * what lets every negative case below read as one assertion — "this did not
 * become the administrator page" — instead of splitting into "the header is
 * missing" and "the header points somewhere else", which are the same thing as
 * far as this middleware's correctness goes.
 */
function rewriteTarget(response: Response): string {
  return response.headers.get('x-middleware-rewrite') ?? ''
}

async function loadProxy(adminLoginPath: string | undefined) {
  vi.resetModules()
  if (adminLoginPath === undefined) delete process.env.ADMIN_LOGIN_PATH
  else process.env.ADMIN_LOGIN_PATH = adminLoginPath
  return (await import('./proxy')).default
}

afterEach(() => {
  delete process.env.ADMIN_LOGIN_PATH
})

describe('the unlisted administrator path', () => {
  it('rewrites to the login page rather than redirecting', async () => {
    const proxy = await loadProxy(SECRET)

    const response = proxy(request(`/${SECRET}`))

    // A rewrite, not a redirect: the address bar must keep the unlisted path,
    // and no locale prefix may appear in it. A 307 here would put the real
    // route in the user's history and in any referrer header that follows.
    expect(response.status).toBe(200)
    expect(rewriteTarget(response)).toContain('/en/admin-login')
    expect(response.headers.get('location')).toBeNull()
  })

  it('tolerates a leading slash in the configured value', async () => {
    const proxy = await loadProxy(`/${SECRET}`)

    const response = proxy(request(`/${SECRET}`))

    expect(rewriteTarget(response)).toContain('/en/admin-login')
  })

  it('does not match a path that merely contains the secret', async () => {
    const proxy = await loadProxy(SECRET)

    const response = proxy(request(`/en/${SECRET}`))

    expect(rewriteTarget(response)).not.toContain('/admin-login')
  })
})

describe('when ADMIN_LOGIN_PATH is unset it fails CLOSED', () => {
  it('rewrites nothing at all', async () => {
    const proxy = await loadProxy(undefined)

    const response = proxy(request(`/${SECRET}`))

    expect(rewriteTarget(response)).not.toContain('/admin-login')
  })

  it('does NOT turn the site root into the administrator login', async () => {
    // The failure mode this guards: an empty secret compared against a stripped
    // pathname would make `/` match, putting the administrator login on the home
    // page of the deployment that forgot to set the variable.
    const proxy = await loadProxy(undefined)

    const response = proxy(request('/'))

    expect(rewriteTarget(response)).not.toContain('/admin-login')
  })

  it('does not break ordinary routing', async () => {
    const proxy = await loadProxy(undefined)

    const response = proxy(request('/en/login'))

    expect(response.status).toBe(200)
  })
})

describe('the ordinary /admin-login path is not a second door', () => {
  it.each(['/en/admin-login', '/ur/admin-login', '/ur-Latn/admin-login', '/admin-login'])(
    '404s %s',
    async (pathname) => {
      const proxy = await loadProxy(SECRET)

      expect(proxy(request(pathname)).status).toBe(404)
    },
  )

  it('does not 404 a path that merely ends with a similar segment', async () => {
    const proxy = await loadProxy(SECRET)

    expect(proxy(request('/en/not-admin-login')).status).not.toBe(404)
  })
})

describe('everything else still reaches next-intl unchanged', () => {
  it('redirects a bare path to the default locale', async () => {
    const proxy = await loadProxy(SECRET)

    const response = proxy(request('/login'))

    // next-intl's own behaviour with `localePrefix: 'always'`. Asserted here
    // because the whole site depends on this branch still being reached.
    expect(response.status).toBe(307)
    expect(response.headers.get('location')).toContain('/en/login')
  })

  it.each(['/en/login', '/ur/dashboard', '/ur-Latn/signup'])(
    'passes %s through',
    async (pathname) => {
      const proxy = await loadProxy(SECRET)

      expect(proxy(request(pathname)).status).toBe(200)
    },
  )

  it('leaves the root redirect intact', async () => {
    const proxy = await loadProxy(SECRET)

    const response = proxy(request('/'))

    expect(response.headers.get('location')).toContain('/en')
  })
})
