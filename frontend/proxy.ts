import createMiddleware from 'next-intl/middleware'
import { NextResponse, type NextRequest } from 'next/server'
import { routing } from './i18n/routing'

/**
 * ⚠️ THIS FILE ROUTES EVERY PAGE ON THE SITE. Breaking it breaks all of them, so
 *    `proxy.test.ts` covers each branch below. Read that file before editing.
 *
 * It used to be four lines wrapping next-intl. It now composes three handlers,
 * in this order, and the order is load-bearing:
 *
 *   1. the unlisted administrator path → REWRITTEN to the login page
 *   2. any direct request for that page → 404
 *   3. everything else → next-intl, untouched
 *
 * Step 3 is unchanged and must stay that way; every locale prefix, every
 * redirect from `/` and every `Link` in the application depends on it.
 */

const intl = createMiddleware(routing)

/**
 * The unlisted administrator login path, WITHOUT a leading slash.
 *
 * ⚠️ NO `NEXT_PUBLIC_` PREFIX, DELIBERATELY. That prefix inlines a value into
 *    the browser bundle at build time, which would publish this path to every
 *    visitor and defeat the entire point of it being unlisted. Middleware runs
 *    on the server, so a server-only variable is readable here.
 *
 * Measured on a production build: this read survives as a literal
 * `process.env.ADMIN_LOGIN_PATH` in the server chunk rather than being folded
 * to a constant, and `grep -rl <the value> .next/` finds nothing at all. So the
 * secret is read at RUNTIME — a change takes effect on restart, no rebuild —
 * and it never enters any build artefact, client or server.
 *
 * ⚠️ IT IS ALSO NOT THE SECURITY CONTROL. `POST /api/auth/admin/login` is: it
 *    refuses non-administrators with a 401 identical to a wrong password. This
 *    variable only decides whether the door is listed, not whether it is locked.
 */
const ADMIN_LOGIN_PATH = process.env.ADMIN_LOGIN_PATH?.replace(/^\/+/, '') ?? ''

/** Where the secret path lands. A route group adds no URL segment. */
const ADMIN_LOGIN_ROUTE = `/${routing.defaultLocale}/admin-login`

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  // 1) The secret path. A REWRITE, not a redirect: the address bar keeps the
  //    unlisted path, and no locale prefix appears in it.
  //
  //    FAILS CLOSED. With `ADMIN_LOGIN_PATH` unset the guard is `'' !== ''`,
  //    which is false, so no rewrite happens and the administrator login is
  //    simply unreachable. That is the correct failure: an unset secret must
  //    never degrade into "every path is the secret path".
  if (ADMIN_LOGIN_PATH !== '' && pathname === `/${ADMIN_LOGIN_PATH}`) {
    return NextResponse.rewrite(new URL(ADMIN_LOGIN_ROUTE, request.url))
  }

  // 2) The ordinary path must not be a second, listed door. Checked on the
  //    SEGMENT rather than with `endsWith`, so `/en/admin-login` and
  //    `/ur/admin-login` are covered while a future `/en/not-admin-login` is
  //    not silently swallowed.
  //
  //    A 404 rather than a redirect, so the response is indistinguishable from
  //    a page that does not exist.
  if (pathname.split('/').at(-1) === 'admin-login') {
    return new NextResponse(null, { status: 404 })
  }

  // 3) Everything else, exactly as before.
  return intl(request)
}

export const config = {
  // Everything except API routes, Next internals, and files with an extension.
  matcher: '/((?!api|_next|_vercel|.*\\..*).*)',
}
