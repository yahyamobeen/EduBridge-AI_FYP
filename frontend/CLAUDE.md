# CLAUDE.md — EduBridge AI frontend

> Authoritative for `frontend/`. When this file and [`/CLAUDE.md`](../CLAUDE.md) disagree, **this
> one wins** for frontend work. Full rules: [`/Claude/RULES.md`](../Claude/RULES.md).

Snapshot: **2026-08-15**.

---

## 1. What this is

Next.js App Router, React, TypeScript, Tailwind. **22 pages** across three route groups —
`(site)`, `(auth)`, `(app)` — and **24 test files** (Vitest). Three locales: `en`, `ur`,
`ur-Latn`, each exactly 426 leaf keys, in identical order.

This application is the interface and nothing else. The data model, the endpoint catalogue and the
authorization rules live in the backend documentation:

- Endpoints → [`../backend/Architecture/api-endpoints.md`](../backend/Architecture/api-endpoints.md)
- Data model → [`../backend/Architecture/database.md`](../backend/Architecture/database.md)

Full picture: [`Architecture/README.md`](Architecture/README.md).

## 2. The update mandate

> **Any change to a route, layout, guard, navigation entry, API (Application Programming Interface)
> wrapper, mock handler or security header MUST update
> [`Architecture/architecture.md`](Architecture/architecture.md) **and**
> `architecture.html` in the SAME change, and append to
> [`/Claude/HISTORY.md`](../Claude/HISTORY.md).**

Lookup table: [`/Claude/DOC-SYNC-MAP.md`](../Claude/DOC-SYNC-MAP.md).

## 3. Conventions that are load-bearing and non-obvious

**`onboarding_state` is the only routing input.** Never a combination of booleans, never
`class_level`, never a guardian status read directly. `lib/auth/onboarding.ts` holds the single
state → route table. **It is not monotonic** — a lapsing trial moves a user *backwards* from
`active`, so a component that evaluates once and caches strands that user on a page they no longer
have rights to. `SessionGuard` re-evaluates on every mount rather than caching, deliberately.

**`SessionGuard` is not a security control.** It is a routing convenience. The gate is enforced at
the interface and database layers. Do not add a check here and consider a resource protected.

It fails **closed**: a 401 and a network error take the same path to `/login`, `me` is assigned
only after both checks pass, and `children` is a render-prop invoked solely when `me !== null`, so
no page content renders before the role check completes.

**`lib/auth/navigation.ts` is a Role-Based Access Control boundary, not styling.** `NAV_BY_ROLE` is
the single source for every sidebar. A new entry needs its role list checked, not just its label.

**The access token lives in a module variable and nowhere else.** Never `localStorage`,
`sessionStorage`, a readable cookie, or a URL — any of those survive the tab and are readable by
injected script. The refresh token is an httpOnly cookie the server sets. **A full page reload
loses the access token and the app recovers via `/auth/refresh`; that is the intended trade-off,
not a bug.** Challenge tokens (`lib/auth/challenge.ts`) follow the same rule, which is why a hard
reload on the two-factor screen sends the user back to sign in.

**Refresh is single-flight and proactive.** N concurrent 401s trigger **one** refresh, not N —
with rotation enabled, all but one would be rejected. Refresh fires at ~80% of the token's lifetime
rather than waiting for a 401, so a long form is not interrupted.

**The 401 → refresh → retry path is allow-listed by error code**, not by status.
`TWO_FACTOR_INVALID` and `PENDING_TOKEN_EXPIRED` are also 401s but mean "wrong code" — retrying
them would resubmit a bad code and burn a lockout attempt.

**A 200 from `/auth/login` is never a credential failure.** It means the password was right and the
journey is incomplete; branch on `status` and move the user forward. Only a 401 means wrong
credentials.

**`script-src` keeps `'unsafe-inline'` — this is a recorded deviation, not an oversight.** The App
Router streams its React payload through inline `<script>` elements; under a bare `script-src
'self'` none of them execute, React never hydrates, and the whole site ships as inert HTML with
every asset returning 200 and an empty console. A per-request nonce is the correct fix and is
unavailable, because these routes are prerendered per locale at build time. Verified both ways on a
clean production build. **Read `next.config.mjs` before tightening it.**

**The `/api` rewrite is what keeps the refresh cookie working.** The cookie is `SameSite=Lax`, and
platform subdomains such as `*.onrender.com` sit on the Public Suffix List — so a frontend and a
backend deployed as sibling subdomains are **cross-site** to the browser and the cookie is never
sent. Proxying `/api/*` through this server makes the API same-origin. **Pointing
`NEXT_PUBLIC_API_BASE_URL` at the backend's public address re-breaks it, silently, in production
only.**

**Forms use plain `useState`.** `react-hook-form` and `zod` are in `package.json` and imported by
**zero source files**. Do not start for one screen. Copy `components/auth/ResetPassword.tsx`:
validation derived during render, a `canSubmit` expression, branch on `ApiError.code` never on
`message`, and errors surfaced through `components/ui/FormFeedback.tsx` so the icon-plus-text-plus-
colour rule in `prd.md` A11Y-1 is not re-implemented per form.

**`setSubmitting(false)` goes in `catch`, not `finally`, on screens that navigate away on success**
— re-enabling the button mid-transition invites a second submission. Screens that stay mounted use
`finally`.

**Use logical Tailwind properties.** `ms`/`me`, `ps`/`pe`, `start`/`end`, `text-start`/`text-end`,
and `rtl:-scale-x-100` on directional icons. `lib/i18n-rules.test.ts` fails the build on any
physical class (`ml-`, `pr-`, `left-0`, `text-left`) because Urdu renders right-to-left.

**`Link` and `useRouter` come from `@/i18n/navigation`**, never from `next/link` or
`next/navigation` — the locale-aware versions are what keep the URL prefix correct.

**The web locale is not the API language enum.** `toApiLanguage` maps `ur-Latn` → `roman_ur`.

## 4. Live data always — there is no mock layer

**Deleted in phase 1b (2026-08-16).** `lib/api/mock/` is gone, along with
`NEXT_PUBLIC_API_MODE`. Do not reintroduce either.

What it was: an in-memory router serving 18 endpoints from eight seeded accounts that all shared the
password `Password123`, plus magic strings — `verify-<user-id>` **minted a session from a URL with
no password**, `123456` passed any two-factor challenge, `BKUP0000` was a working backup code. It was
the **default** whenever `NODE_ENV` was not `production`, and `API_MODE === 'mock'` was tested
*before* `NODE_ENV`, so an explicit flag shipped those credentials out of a production build.

### You need a backend running

`NEXT_PUBLIC_API_BASE_URL` is now **required** — local (`http://localhost:8000/api`) or the deployed
service. Pages that load data will not work without one, and signup fails first, because
`(site)/signup/student/page.tsx` fetches reference data during server rendering.

⚠️ **`NEXT_PUBLIC_*` is inlined at build time. Restart `next dev` after changing it.**

### The empty base URL is load-bearing in the browser

`client.ts` falls back to `''` so requests go out relative and are rewritten by `next.config.mjs`,
which is what keeps the refresh cookie same-site (§3). **Do not replace it with an absolute URL.**
On the *server* there is no origin to be relative to, so `resolve()` throws a named error telling you
which variable to set — the mock layer used to hide that failure by defaulting on.

### When adding an endpoint

Add the types to `lib/api/types.ts` and the wrapper to `lib/api/endpoints.ts`. Tests stub
`globalThis.fetch` and exercise the real transport — see `lib/api/client.test.ts`. There is no second
implementation of the contract to keep in step any more, which was the point.

## 5. Testing

```bash
npm test && npm run build
```

`npm run build` includes the TypeScript check. Tests are colocated as `<Name>.test.tsx`, use
Vitest with `@testing-library/react`, wrap components in `NextIntlClientProvider` with the **real**
`messages/en.json` so assertions reference `en.*.*` rather than hard-coded strings, and query by
accessible role or label rather than test ids.

There is **no message-parity test** across the three locale files. The house pattern for covering a
new screen is the `onError` assertion in `components/landing/Landing.test.tsx` — render under all
three locales and assert next-intl's error callback was never called, since a missing key is
reported there rather than thrown.

## 6. Known defects

Recorded rather than hidden — see
[`Architecture/architecture.md`](Architecture/architecture.md) for detail. `VerifyEmail` reproduces
the React StrictMode deadlock `SessionGuard` documents having fixed. An unvalidated
`onboarding_state` reaches `router.replace(undefined)`. `error.tsx` logs the error object it refuses
to render.

**Fixed and recorded so nobody re-audits:** the `admin` role routing to a page that did not exist
(phase 1b built it), the backup-code download silently producing no file, and sign-out no-opping on
a network failure (both phase 1).

## 7. Administrators do not use the public identity surface

`admin` is not accepted by `POST /auth/register` and not accepted by `POST /auth/login` either.
Administrators sign in at `POST /auth/admin/login`, reached through a page the middleware serves at
a server-only unlisted path (`ADMIN_LOGIN_PATH` — **never** `NEXT_PUBLIC_`, which would publish it).

**Both refusals are a 401 identical to a wrong password.** Not a 403: a distinguishable answer would
let anyone submit an address to the public form and read the status code to learn whether it belongs
to an administrator.

⚠️ **The unlisted path is not a security control**, any more than `SessionGuard` is. The endpoint's
role check is. `proxy.ts` also 404s the ordinary `/admin-login` route so it is not a second door —
read `proxy.test.ts` before touching that file, because it routes every page on the site.
