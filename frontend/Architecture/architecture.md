# Frontend Architecture

Next.js App Router client for EduBridge AI — screens, routing and a transport layer over the FastAPI backend.

> **Snapshot date: 2026-08-15.** Describes commit `eea0e74` on branch `fix-epic-1` (`git log -1 --format=%h` → `eea0e74`), plus the uncommitted Phase 0 documentation.
> Source of truth is the code. Every `file:line` below was opened and verified at this snapshot; paths are relative to `frontend/`.

---

## Measured facts

Every count here has the command that produced it beside it. Run from `frontend/`.

| Measure | Value | Command |
|---|---|---|
| Pages | **22** | `find app -name "page.tsx" \| wc -l` |
| Route groups | **3** | `find app -type d -name "(*)" \| wc -l` |
| Test files | **24** | `find . -path ./node_modules -prune -o -path ./.next -prune -o \( -name "*.test.ts" -o -name "*.test.tsx" \) -print \| wc -l` |
| Locales | **3** (`en`, `ur`, `ur-Latn`) | `ls messages/` |
| Leaf message keys per locale | **426**, identical across all three and in the same order | see `README.md` § *How those numbers were measured* |

`node_modules/` and `.next/` are excluded from every count.

---

## Stack

| Layer | Choice | Where |
|---|---|---|
| Framework | Next.js `^16.2.12` (App Router) | `package.json:19` |
| UI runtime | React `^19.2.8` | `package.json:21` |
| Language | TypeScript `^6.0.3` | `package.json:48` |
| Styling | Tailwind CSS `^3.4.19` | `package.json:47` |
| Internationalisation | next-intl `^4.13.4` | `package.json:20` |
| Tests | Vitest `^4.1.10` + Testing Library | `package.json:49`, `vitest.config.mts` |

**Two dependencies are installed and imported by zero source files**: `react-hook-form` (`package.json:23`), `zod` (`package.json:24`) and their resolver bridge `@hookform/resolvers` (`package.json:18`). Every form in this application is plain `useState`. That is a deliberate choice, not an oversight — the forms here are short and the validation is server-authoritative — but the packages are still in the dependency tree and a future contributor should know they are unused rather than assume a convention exists.

`package.json:26-30` carries an `overrides` block lifting `postcss` and `sharp` off the versions Next pins, with the reason recorded inline: `npm audit fix --force` "resolves" those advisories by installing `next@9`, which is not a fix.

---

## The route tree

Everything lives under one dynamic `[locale]` segment. `app/layout.tsx:9-11` is a bare pass-through, because `<html>` cannot live there — `lang` and `dir` both depend on the locale, which is only known inside `[locale]`. The real document shell is `app/[locale]/layout.tsx:32-60`.

```
app/
  layout.tsx                     pass-through (:9-11)
  [locale]/
    layout.tsx                   <html lang dir>, NextIntlClientProvider, SkipLink (:32-60)
    error.tsx                    locale-wide error boundary (:20-71)
    not-found.tsx                localized 404, renders its own chrome (:15-38)
    (site)/    layout.tsx        TopNav + main + Footer (:12-22)
    (auth)/    layout.tsx        bare main, no chrome (:11-17)
    (app)/     layout.tsx        bare main, no chrome (:10-16)
```

`app/[locale]/layout.tsx:17-19` pre-renders all three locales at build time via `generateStaticParams`. `:38` sends an unknown locale to `notFound()` rather than falling back to English — a student who lands on `/pk/login` is told the page is wrong instead of being handed a language they may not read. `:41` calls `setRequestLocale`, without which every page opts into dynamic rendering; that static prerendering is what the Content Security Policy section below turns on.

### The three route groups

A route group adds **no path segment**. `/login` is `/login` whether or not it sits inside `(auth)`. The split exists purely so the three surfaces can have different chrome.

#### `(site)` — the public marketing surface

`app/[locale]/(site)/layout.tsx:12-22` renders `TopNav`, `main`, `Footer`. Seven pages:

| Route | File |
|---|---|
| `/` | `(site)/page.tsx` |
| `/signup` | `(site)/signup/page.tsx` |
| `/signup/student` | `(site)/signup/student/page.tsx` |
| `/signup/parent` | `(site)/signup/parent/page.tsx` |
| `/signup/teacher` | `(site)/signup/teacher/page.tsx` |
| `/coming-soon/[slug]` | `(site)/coming-soon/[slug]/page.tsx` — 21 allow-listed slugs at `:15-41` |
| catch-all | `(site)/[...rest]/page.tsx:8-10` — calls `notFound()` so an unmatched path renders the *localized* 404 |

`/coming-soon/[slug]` is the destination for every prototype link whose product area is not built yet. `:61` rejects any slug outside the literal list with `notFound()`; `:53-55` statically generates all 21 slugs × 3 locales. It exists because `href="#"` reads as broken and deleting the links loses the prototype's navigation.

#### `(auth)` — the transactional screens

`app/[locale]/(auth)/layout.tsx:11-17` is **deliberately bare**: no top nav, no footer. The reason is recorded at `:3-10` — a half-authenticated user has nowhere legitimate to navigate to, and offering the marketing nav mid-challenge is an invitation to abandon the flow. Each screen carries its own minimal footer links instead (`components/auth/AuthFooterLinks.tsx`).

Ten pages:

| Route | File | Notes |
|---|---|---|
| `/login` | `(auth)/login/page.tsx` | |
| `/login/2fa` | `(auth)/login/2fa/page.tsx` | Reachable only from `/login`, which puts the `pending_token` in memory first (`:13-18`) |
| `/onboarding/email` | `(auth)/onboarding/email/page.tsx` | |
| `/onboarding/2fa` | `(auth)/onboarding/2fa/page.tsx` | |
| `/onboarding/guardian` | `(auth)/onboarding/guardian/page.tsx` | Class 9–10 students only; the backend never puts a Class 11–12 student in that state (`:13-18`) |
| `/onboarding/plan` | `(auth)/onboarding/plan/page.tsx` | The one step a user can reach *after* having been `active` (`:13-17`) |
| `/verify-email` | `(auth)/verify-email/page.tsx` | |
| `/forgot-password` | `(auth)/forgot-password/page.tsx` | |
| `/reset-password` | `(auth)/reset-password/page.tsx` | |
| `/guardian/confirm` | `(auth)/guardian/confirm/page.tsx` | Where the invitation email lands; authenticated as the **parent** (`:16-21`) |

#### `(app)` — the authenticated application, and why it renders no chrome

`app/[locale]/(app)/layout.tsx:10-16` renders a bare `<main>`. The reason is at `:3-9`:

> No chrome here: each dashboard renders its own sidebar through `DashboardShell`, because the sidebar's contents depend on the role, which is only known once `SessionGuard` has resolved the identity.

This is the structural consequence of the guard being a **client-side, render-prop** component. The role arrives from `GET /auth/me` after mount. A layout is rendered above the page, before that answer exists, and a server layout cannot read it at all. Putting a sidebar there would mean either rendering an empty shell and then filling it — a visible layout shift on every dashboard entry — or picking a default role, which is exactly the copy-paste mistake `navigation.ts` exists to prevent. So the chrome moves *inside* the guard, where `me` is already resolved, and the layout does nothing but reserve the flex column.

Three pages, one per role that has a dashboard:

| Route | File | Component | `allow` |
|---|---|---|---|
| `/dashboard` | `(app)/dashboard/page.tsx:13-17` | `StudentDashboard` | `['student']` — `components/app/Dashboards.tsx:34` |
| `/teacher` | `(app)/teacher/page.tsx:13-17` | `TeacherDashboard` | `['teacher']` — `Dashboards.tsx:80` |
| `/parent` | `(app)/parent/page.tsx:13-17` | `ParentDashboard` | `['parent']` — `Dashboards.tsx:103` |
| `/admin` | `(app)/admin/page.tsx:13-17` | `AdminDashboard` | `['admin']` — `Dashboards.tsx:145` |

**`/admin` was built in phase 1b**, which closes defect **A6**. Administrators reach it after signing
in at an unlisted path served by `(auth)/admin-login/page.tsx` — see *The unlisted administrator
login* below.

The dashboards are shells. `Dashboards.tsx:8-19` records why: no dashboard data endpoint exists in the contract, so the panels name what will live there and say plainly that it is not available yet, rather than rendering the mockups' invented 78% exam readiness. `PlaceholderCard` (`components/app/DashboardShell.tsx:144-185`) renders the "not yet available" pill. What *is* real on these pages is the navigation and the role boundary.

---

## `SessionGuard` — the gate on every authenticated route

`components/app/SessionGuard.tsx`.

### Shape

It is a **render-prop** component, not a wrapper and not a hook:

```ts
// components/app/SessionGuard.tsx:29-36
export function SessionGuard({
  children,
  allow,
}: {
  children: (me: MeResponse) => ReactNode
  /** Roles permitted on this route. */
  allow: Role[]
})
```

`children` is a *function* of the resolved identity. That shape is load-bearing: the page body cannot be constructed at all until `me` exists, so there is no branch on which a component can render with an undefined user. Every call site passes an inline arrow — `Dashboards.tsx:35`, `:81`, `:109`.

### The three checks, in order

One identity check per mount, in a `useEffect` with an empty dependency array (`:42-97`):

1. **No session → `/login`.** Any failure to establish identity is caught at `:73-77` and treated as "not signed in". The client has already attempted a refresh by this point, so there is nothing further to recover from.
2. **Onboarding incomplete → the step that completes it.** `:64-67`: if `identity.onboarding_state !== 'active'`, `router.replace(routeForOnboardingState(identity.onboarding_state, identity.role))` and return.
3. **Wrong role → that role's own dashboard.** `:68-71`: if `!allow.includes(identity.role)`, `router.replace(dashboardFor(identity.role))` and return. A parent who opens `/dashboard` is sent to `/parent`, not to an error page.

Only if all three pass does `:72` call `setMe(identity)`, and only then does `:113` render `children(me)`.

Each of the four cases has a test: `SessionGuard.test.tsx:49-53`, `:55-59`, `:61-65`, `:67-72`.

### It fails closed on every path

`:99-111`: while `me === null`, the component renders a `role="status"` region and **no page content** — `checked ? t('redirecting') : t('loading')`. There is no branch that renders `children` before the identity resolves, no `me ?? fallbackUser`, and no optimistic path. A hung request renders "Loading…" forever; a rejected request renders "Redirecting…" and navigates. Neither shows a page. `SessionGuard.test.tsx:104-111` asserts that a permanently pending promise produces no page content.

### It is **not** a security control

Stated in the file's own header at `:25-27`, and repeated here because it is the single most misreadable thing in this application:

> None of this is a security control. The gate is enforced at the API and RLS layers, so calling the endpoint directly is still refused; this only stops the UI showing a user a page they cannot use.

`SessionGuard` runs in the browser. Its inputs come from a `fetch` the user controls, its decisions are `router.replace` calls the user can skip, and its entire bundle is readable. It prevents a *confusing* screen, not an *unauthorized* read. Everything that actually protects data is in `backend/Architecture/architecture.md` (the application layer) and `backend/Architecture/database.md` (the Row-Level Security layer). **Register section B records that the database layer does not currently hold**, which makes it more important, not less, that nobody counts this file as a second line of defence.

### The StrictMode note

`:43-56` records a real bug and its fix. The obvious implementation — a `started` ref to make the effect idempotent — **deadlocked in development**. `reactStrictMode: true` (`next.config.mjs:136`) makes React mount, unmount and remount every component. The unmount set `cancelled`, discarding the in-flight response; the remount found `started.current` still `true` (refs survive the double-invoke) and returned early. The first request's result was thrown away, the second was never made, and neither `setMe` nor `setChecked` ever ran. Every dashboard sat on "Loading…" forever with a healthy 200 in the network tab — and only in development, so nothing in continuous integration could see it.

The fix is the empty dependency array plus a plain `let cancelled` closure variable (`:57`, `:83-85`), which is re-created per mount and therefore does not survive the double-invoke. `:86-97` explains why the array is empty rather than `[router]`: `router` is a fresh object each render, so keying on it would re-run the identity check continuously.

**The same pattern is reproduced, unfixed, in `VerifyEmail`.** See defect **D5**.

---

## Onboarding routing

`lib/auth/onboarding.ts` is the **one place** onboarding routing is decided.

### `onboarding_state` is the only input

`:3-11`:

> Routing is driven by `onboarding_state` from the identity endpoint and nothing else — never from `class_level`, never from a combination of booleans.

That is why a Class 11–12 student has **no code path** that can render the parental gate: the backend never sets the state for them, so the frontend has nothing to render it from. There is no `if (classLevel <= 10 && !guardianVerified)` anywhere in this application, and there must never be one — a client-side re-derivation of a server-side gate is a second source of truth that will drift.

`onboarding_state` is a five-value union on the client (`lib/api/types.ts:12-17`) and is derived server-side per request, never stored.

### State → route

`lib/auth/onboarding.ts:24-29` and `:13-18`:

| `onboarding_state` | Route | Source |
|---|---|---|
| `email_verification_pending` | `/onboarding/email` | `onboarding.ts:25` |
| `two_factor_enrollment_pending` | `/onboarding/2fa` | `onboarding.ts:26` |
| `guardian_link_pending` | `/onboarding/guardian` | `onboarding.ts:27` |
| `plan_selection_pending` | `/onboarding/plan` | `onboarding.ts:28` |
| `active` | `dashboardFor(role)` | `onboarding.ts:32` |

And `dashboardFor` (`:13-22`):

| Role | Dashboard |
|---|---|
| `student` | `/dashboard` |
| `teacher` | `/teacher` |
| `parent` | `/parent` |
| `admin` | `/admin` |

Three functions read that table:

- `routeForOnboardingState(state, role)` (`:31-33`) — for a caller that has both. `SessionGuard.tsx:65`.
- `pendingOnboardingRoute(state)` (`:43-45`) — returns `null` for `active`. Exists so a caller that has a state but **no role** — the two-factor challenge, whose response carries `onboarding_state` and nothing else (`lib/api/types.ts:119-124`) — can route without inventing one. `TwoFactorChallenge.tsx:175`, `TwoFactorEnrollment.tsx:136`, `VerifyEmail.tsx:61`.
- `isOnboardingComplete(state)` (`:54-56`) — a named predicate for `state === 'active'`.

### It is **not monotonic**

This is the rule that makes the guard different from the obvious implementation, recorded at `onboarding.ts:47-53` and again at `SessionGuard.tsx:13-18`:

> A student reaches `active`, uses the app for fourteen days, and then the trial lapses and the server puts them back into `plan_selection_pending`.

Onboarding is a **state**, not a **checklist**. A user moves *backwards* through it. Any consumer that caches `active` — a context set once on login, a `hasOnboarded` boolean in local storage, a guard written as "check once, then trust" — strands that user on a page they no longer have rights to, with every API call returning 403 `SUBSCRIPTION_REQUIRED` and no route out.

The defence is that the state is re-read on **every mount** and never remembered across one. `SessionGuard.test.tsx:90-101` asserts exactly this: it renders the guard with an `active` student, unmounts, flips the mock to `plan_selection_pending`, renders again, and asserts both the redirect and that `getMe` was called twice.

The transport client carries the same rule at a lower level: a 403 `SUBSCRIPTION_REQUIRED` on any request redirects to `/onboarding/plan` (`lib/api/client.ts:186-190`), so a trial that lapses *mid-session* is caught without waiting for a remount.

---

## `navigation.ts` is a Role-Based Access Control boundary

`lib/auth/navigation.ts`. Its header says so in the first sentence (`:3-31`):

> THIS FILE IS AN RBAC BOUNDARY, not a styling concern.

`NAV_BY_ROLE` (`:44-75`) is a `Record<Role, NavItem[]>`. `DashboardShell` builds every sidebar from it (`components/app/DashboardShell.tsx:41`, rendered at `:69-85`) and from nothing else. That single-source construction is the mechanism: an item cannot leak across roles by copy-paste, because there is no per-role markup to paste into.

Three decisions it encodes, each of which a shared component tree makes easy to get wrong:

**(a) The parent surface is read-only.** `:67-73` — dashboard, my child, progress, how to help, settings, help. No tutor, no session replay, no planner write. The supplied mockups shipped **one student sidebar pasted into all three dashboards**, which handed parents a "Play Session" button that replays a child's AI tutor conversation. `GET /api/tutor/sessions/{id}` is student-owner-only and the requirements forbid a parent reading chat content — so that control was not a dead link, it was a privacy violation with a button on it.

**(b) The teacher surface has no tutor entry.** `:56-66`. The requirements once granted teachers tutor access "for own testing" while `POST /api/tutor/ask` has always been scoped to gate-verified students. The technical design document won.

**(c) The student surface must expose My Classes.** `:52`. Students are guaranteed the right to see who can view them and to leave any space at any time. No mockup had an entry for it, and a right with no route to it is not a right.

`lib/auth/navigation.test.ts` is described in its own header (`:8-18`) as *the highest-value regression test in the frontend*. `:19-34` asserts the parent navigation contains no href and no key matching `/tutor/`, `/session|replay|play/`, `/planner/`, `/practice/`, `/quiz/` or `/subject|curriculum/`. `:36-46` asserts the teacher surface has no tutor entry. `:48-54` asserts the student surface has My Classes. `:67-81` asserts every key has a translated label in all three locales.

`ROLE_ACCENT` (`:78-83`) sits in the same file and *is* styling — one Tailwind text-colour class per role. It is the exception that proves the rule: it is here because it is keyed by `Role`, and keeping every role-keyed record together is what makes an incomplete role obvious.

---

## The API (Application Programming Interface) client

`lib/api/client.ts` is the single entry point for every call. `lib/api/endpoints.ts` wraps it in typed functions so no screen hand-writes a path or a shape. `lib/api/types.ts` is transcribed from the contract, so a response shape that drifts from it is a type error rather than an integration surprise.

### Live data always — the mock layer was deleted

`lib/api/client.ts` used to select a hand-rolled in-memory backend from `NEXT_PUBLIC_API_MODE`.
**Phase 1b deleted it entirely** — 841 lines across `lib/api/mock/{index,db,db.test}.ts`, plus the
branch, plus the flag from `.env.example`, `vitest.config.mts`, `render.yaml` and the CI workflow.

What it was, recorded so nobody rebuilds it: an in-memory router serving 18 endpoints from eight
seeded accounts that all shared one password, plus magic strings — `verify-<user-id>` **minted a
session from a URL with no password**, `123456` passed any two-factor challenge, and `BKUP0000` was a
working backup code. It was the **default** whenever `NODE_ENV` was not `production`, and the
`'mock'` flag was tested *before* `NODE_ENV` — so setting it explicitly shipped those credentials out
of a production build. That is what defect **C4** was, and deleting the layer converts the guarantee
from a configuration invariant into a structural one: there is no mock to select.

#### The configuration hole it was hiding, now named instead of hidden

```ts
// lib/api/client.ts
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''

function resolve(path: string): string {
  if (BASE_URL) return `${BASE_URL}${path}`
  if (typeof window === 'undefined') {
    throw new Error('NEXT_PUBLIC_API_BASE_URL is not set, and a relative API path cannot be…')
  }
  return path
}
```

The mock default existed *because* an unset base URL produces a relative path Node cannot parse on
the server. **The empty string is still load-bearing in the browser**: relative `/api/...` goes
through the `next.config.mjs` rewrite, and that rewrite is what keeps the refresh cookie same-site.
Pointing `NEXT_PUBLIC_API_BASE_URL` at the backend's public address re-breaks it silently, in
production only. So the fix is **server-side only**: no `window` and no base URL now throws a named
error naming the variable to set, rather than failing three frames deep inside `fetch`.

What this costs, stated plainly: a developer with a clean checkout and no backend running no longer
gets a working application. Pages that load data fail, and signup fails first, because
`(site)/signup/student/page.tsx` fetches reference data during server rendering.

### Proactive refresh at 80% of token lifetime

`apiFetch` refreshes **ahead of use** rather than waiting to be told (`:152-159`):

```ts
if (init.bearer === undefined && getAccessToken() !== null) {
  if (isExpired() || shouldRefreshAhead(lastLifetimeSeconds)) {
    await refreshOnce()
  }
}
```

`shouldRefreshAhead` (`lib/auth/tokenStore.ts:45-50`) reconstructs the issue time from the stored absolute expiry and the original `expires_in`, then compares elapsed time against `REFRESH_AT_FRACTION` — `0.8` (`tokenStore.ts:18`). `lastLifetimeSeconds` is remembered at `client.ts:28` and set by `rememberSession` at `:30-33`, because the store keeps only the absolute expiry.

The point is stated at `client.ts:153-154`: a long form must not be interrupted by a redirect the user did not cause. Waiting for a 401 means the interruption lands mid-typing.

### Single-flight refresh, and why rotation makes it necessary

```ts
// lib/api/client.ts:76-81
export function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}
```

The module-level `refreshInFlight` (`:69`) means N concurrent 401s trigger **one** refresh, not N. Every caller awaits the same promise.

The reason is refresh-token **rotation**: each successful refresh invalidates the token it consumed and issues a new one. Without single-flight, a dashboard firing several requests at once sends a burst of refreshes; the first consumes the cookie, and every other one presents a token the server has already retired. On a backend that treats a retired token as theft, that burst is indistinguishable from an attack — it signs the user out mid-session and writes a false reuse-detection audit row. `client.test.ts:76-94` fires three concurrent requests that each 401 and asserts exactly one `/auth/refresh` call.

`performRefresh` (`:83-94`) deliberately bypasses `apiFetch` and calls `rawRequest` directly (`:85-87`): a refresh that itself 401s must not recurse back into the retry path. On failure it calls `endSession()` and returns `false`.

**A caveat worth recording:** this guard is per browser tab. Two tabs of the same application hold two independent module states and can still race a rotating refresh (register **D2**).

### The retry allow-list

Not every 401 is worth retrying. `lib/api/errors.ts:90-102`:

```ts
const REFRESHABLE_401_CODES = new Set<string>(['UNAUTHENTICATED', 'UNKNOWN'])

export function isRefreshableAuthError(error: ApiError): boolean {
  return error.status === 401 && REFRESHABLE_401_CODES.has(error.code)
}
```

An **allow-list**, not a status check. `TWO_FACTOR_INVALID` and `PENDING_TOKEN_EXPIRED` are also 401s, but they mean the submitted code was wrong or its challenge died. Refreshing and retrying those would resubmit a bad code and burn one of the user's lockout attempts. `UNKNOWN` is included because `toApiError` (`:79-88`) assigns it when a proxy, gateway or crash returns HTML or an empty body — a transport failure that a fresh token may well fix.

The retry itself is at `client.ts:168-170`, guarded three ways: not a challenge credential (`init.bearer === undefined`), not opted out (`!init.noRetry`), and on the allow-list. It runs **once** — `rawRequest` is called directly, not `apiFetch`, so there is no loop. `client.test.ts:96-105` asserts the original path is hit exactly twice and then gives up.

`noRetry` is documented at `client.ts:105-113` and used at exactly one call site: `login` (`endpoints.ts:61`). On `/auth/login` a 401 means the password was wrong, so refreshing would fire a guaranteed-to-fail request on every typo.

### Transport-level onboarding redirects

`GATE_PENDING` and `SUBSCRIPTION_REQUIRED` are both 403s that mean "authenticated, but an onboarding precondition is unmet". Neither is an error to show; both are a signal to move the user. `client.ts:182-198`:

| Error code | Redirect target |
|---|---|
| `GATE_PENDING` | `/onboarding/guardian` |
| `SUBSCRIPTION_REQUIRED` | `/onboarding/plan` |
| any other 403 | none — left to the screen to render |

`:193-195` suppresses the redirect when `currentPath()` already ends with the target, because the gate page itself calls guardian endpoints and would otherwise loop.

The client must not import the router — that would make it untestable outside React and couple the transport to the framework — so a handler is **registered** instead (`:40-56`):

```ts
export function setNavigationHandler(fn: NavigateFn, pathReader: () => string): void
```

> **Verified, and worth knowing: `setNavigationHandler` is called from no application code.** The only call sites are `lib/api/client.test.ts:138`, `:148`, `:159` and `:169`. A repository-wide search outside `node_modules` and `.next` finds no provider that registers it. `navigate` is therefore `null` at runtime, and `handleOnboardingRedirect` returns at its first line (`:183`) on every real request. The mechanism is built and tested but not wired; the redirects it describes do not currently fire in the running application. `SessionGuard` still catches the same conditions on the next mount, so the user is not stranded — the loss is that a mid-session lapse is not caught until a navigation.

---

## Credential storage

Three kinds of credential, three storage rules, all of them narrower than the obvious choice.

| Credential | Where it lives | Survives a reload? |
|---|---|---|
| Access token | Module variable, `lib/auth/tokenStore.ts:14` | **No** |
| Refresh token | `httpOnly` cookie set by the server | **Yes**, but JavaScript can never read it |
| `pending_token` (two-factor challenge) | Module variable, `lib/auth/challenge.ts:34` | **No** |
| `enrollment_token` (two-factor enrolment) | Module variable, `lib/auth/challenge.ts:35` | **No** |
| Unverified email address | Module variable, `lib/auth/challenge.ts:43` | **No** |

### The access token

`lib/auth/tokenStore.ts:1-12`:

> The access token lives in a module-level variable and nowhere else. Never localStorage, sessionStorage, a readable cookie, or a URL: any of those survive the tab and are readable by injected script.

`accessToken` and `expiresAtMs` are two `let` bindings at `:14-15`. There is no persistence layer under them. The repository contains no `localStorage`, no `sessionStorage` and no `document.cookie` anywhere in application code — that was verified in the Epic 1 sweep and recorded in the register's *verified correct* list.

The refresh token is an `httpOnly` cookie the server sets. JavaScript cannot read it at all, which is the property that makes it safe to persist when the access token is not.

The consequence is stated at `tokenStore.ts:9-11`: **a full page reload loses the access token**, and the application recovers by calling `/auth/refresh` with the cookie. That is the intended trade-off, not a bug — and it is why `rawRequest` sends `credentials: 'include'` (`client.ts:130-131`) on every call.

`endpoints.ts:175-177` is the one place a token enters the application, so no screen has to remember that `expires_in` drives proactive refresh.

### The challenge tokens, and the deliberate reload consequence

`lib/auth/challenge.ts:3-17`:

> `pending_token` and `enrollment_token` are bearer credentials: presenting one completes an authentication step. So they follow exactly the same storage rule as the access token — a module variable and nowhere else.

And the consequence, spelled out as design rather than defect:

> a hard reload on `/login/2fa` loses the challenge, and the screen sends the user back to `/login` to sign in again. A token that survived a reload would also survive the user walking away from a shared device.

Shared devices are the operative case here. This is a product used on family phones and school computers; a challenge credential that outlives the tab outlives the user's attention. `/login/2fa` records the same thing from the page side (`(auth)/login/2fa/page.tsx:13-18`): opening it directly renders nothing and returns to sign-in, because the token cannot be recovered from a URL or from storage **by design**.

`unverifiedEmail` (`:37-43`) is kept for a subtler reason: `status: 'email_verification_required'` returns a **masked** address, and a masked address cannot be submitted to `/auth/email/resend`. The unmasked address the user typed is the only usable value.

`clearAllChallenges()` (`:77-82`) is called once a session exists, so a spent challenge cannot be replayed — `TwoFactorChallenge.tsx:173`, immediately after `startSession` at `:172`. The order is deliberate (`:169-171`): the session is stored before the spent challenge is dropped, so a failure between the two cannot leave the user holding neither credential.

Challenge credentials travel as `init.bearer` (`client.ts:103-104`, `:127`), which is what excludes them from proactive refresh (`:155`) and from refresh-and-retry (`:168`). Refreshing cannot help a challenge token, and retrying would waste an attempt. `client.test.ts:126-132` asserts a `bearer` request never triggers a refresh.

---

## Internationalisation

### Three locales

`i18n/routing.ts:16-37` defines `['en', 'ur', 'ur-Latn']` with `en` as default. Messages live in `messages/en.json`, `messages/ur.json`, `messages/ur-Latn.json` — **426 leaf keys each, identical across all three**, and in the same order — phase 1 added `downloadFailed` (A7) and phase 1b added 27 administrator keys.

`localeDetection: false` (`:36`). Left on, next-intl negotiates from `Accept-Language` and a `NEXT_LOCALE` cookie, so a browser configured for Urdu — entirely normal in this audience — would be redirected to `/ur` before the visitor had chosen anything. Turning detection off makes `/` resolve to `/en` for everyone and makes language an explicit choice. The trade-off, accepted deliberately at `:31-34`: this also disables the cookie, so a returning visitor who previously chose Urdu lands on `/` in English again. They stay in Urdu while navigating, because every link carries the locale prefix.

`i18n/navigation.ts:9` exports locale-aware `Link`, `redirect`, `usePathname`, `useRouter` and `getPathname`. **Always import from there**, never from `next/link` or `next/navigation`, or the locale prefix is dropped and the user silently falls back to English mid-journey (`:4-8`). `proxy.ts:4` mounts the next-intl middleware; `:6-9` excludes `/api`, Next internals and any path with a file extension.

`components/layout/LanguageSwitcher.tsx:18-51` is a segmented control of **real links**, not a JavaScript dropdown — so switching works without JavaScript, costs one tap rather than two, and survives a slow connection. `:20` calls the locale-aware `usePathname`, which returns the path *without* the prefix, and `:31` feeds it straight back as the `href`, so the same page is preserved across a switch. `:36` sets `lang="ur"` on the Urdu option so the endonym renders in the Naskh face even inside an English page.

### Right-to-left for Urdu only

`i18n/routing.ts:64-80`:

```ts
const RTL_LOCALES = new Set<string>(['ur'])
export function isRtl(locale: string): boolean { return RTL_LOCALES.has(locale) }
export function dirFor(locale: string): 'rtl' | 'ltr' { return isRtl(locale) ? 'rtl' : 'ltr' }
```

**Roman Urdu is Urdu written in Latin script, so it reads left-to-right.** Mirroring it would be a defect, not a feature. This is the single place that decision is encoded; nothing else may test the locale string to work out direction. `app/[locale]/layout.tsx:51` is the only consumer that matters — `<html lang={locale} dir={dirFor(locale)}>`.

`app/fonts.ts:36-38` reads the same predicate: the Urdu Naskh face is loaded with `preload: false` (`:30`) and applied only for right-to-left locales, so an English or Roman-Urdu visitor never downloads a large Arabic-script font they cannot read.

### The logical-property lint rule

`lib/i18n-rules.test.ts` is a **test that behaves like a lint rule**. Its header (`:5-16`):

> A single `ml-2` looks fine in English and silently breaks the Urdu layout, which nobody notices until someone reads the page in Urdu. The prototypes are entirely physical (`pl-10`, `left-0`, `text-left`), so this catches a class copied straight across.

It walks `app/` and `components/` (`:18`, `:24-32`), skipping test files, and fails any non-test `.ts`/`.tsx` file whose `className` lines match:

```
// lib/i18n-rules.test.ts:21-22
/(?:^|[\s"'`:[])(?:-)?(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r)(?:-[a-z0-9./[\]%-]+)?(?=[\s"'`\]]|$)|text-(?:left|right)/
```

`:43-45` restricts the check to lines containing `className` or `class=`, so prose in a comment may still say "left". `:39` runs it as one test case per file, so a failure names the offending file and line rather than a single opaque assertion. `:35-37` guards against the walker silently finding nothing.

The permitted replacements are the logical properties: `ms`/`me`, `ps`/`pe`, `start`/`end`, `text-start`/`text-end`, `border-s`/`border-e`. A new screen is correct in Urdu by construction rather than by review. Real usage: `DashboardShell.tsx:92` (`text-start`), `:105` (`border-e`), `:118` (`end-4`).

Where mirroring is genuinely wrong, it is opted out explicitly. `BackupCodes.tsx:63-67` marks the code grid `force-ltr` because backup codes are Latin-alphanumeric strings that must not reorder inside an Urdu page. `error.tsx:64` does the same for the digest.

### Web locale → API enum

The two vocabularies are **deliberately different** (`i18n/routing.ts:3-15`):

| Web locale | API / database `language_code` |
|---|---|
| `en` | `en` |
| `ur` | `ur` |
| `ur-Latn` | **`roman_ur`** |

The database enum and the API contract use `roman_ur`. That is a fine internal identifier but **not a valid BCP-47 language tag**: `Intl.NumberFormat('roman_ur')` throws `RangeError`, and `<html lang="roman_ur">` is invalid, so a screen reader cannot tell what language the page is in. The web layer therefore uses `ur-Latn` — the correct tag for Urdu in Latin script — and maps at the API boundary.

Both directions live in one file: `LOCALE_TO_API` (`:44-48`) and `API_TO_LOCALE` (`:50-54`), exposed as `toApiLanguage` (`:56-58`) and `fromApiLanguage` (`:60-62`). `lib/api/types.ts:23-24` re-declares `ApiLanguage` with a comment pointing back here.

`LOCALE_LABELS` (`:83-87`) names each language in its own script — `English`, `اردو`, `Roman Urdu` — never translated.

---

## The Content Security Policy deviation

`next.config.mjs:59-97` sets four security headers on every path (`:147-149`). One directive deviates from the obvious hardening, deliberately:

```
// next.config.mjs:81
script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com   [+ 'unsafe-eval' in dev]
```

### Why `'unsafe-inline'` stays

`next.config.mjs:3-30` records it in full. Summarised:

- The App Router **streams its React payload through inline `<script>` elements**. Under a bare `script-src 'self'` every one of them is blocked, React never hydrates, and the entire site ships as dead HTML — no form accepts input, no button responds.
- **It fails silently.** Every asset returns 200 and the console stays empty. That is why it survived five phases unnoticed.
- **Verified both ways on a clean production build.** The tightened value was applied, built and opened; the application was inert. The current value was applied, built and opened; it works.

The correct fix is a **per-request nonce**, and it cannot be used here. A nonce must differ per response, so the page must be rendered per request — but these routes are prerendered per locale at build time (`app/[locale]/layout.tsx:17-19`, `:41`). Forcing them dynamic would trade the static prerendering the accessibility and performance requirements depend on — a fast first paint on a mid-tier Android over Slow 3G — for a directive that stops a subset of cross-site scripting payloads. Revisit if the auth routes ever become dynamic for another reason.

`'unsafe-eval'` is **development only** (`:66-72`): React uses `eval()` in development to reconstruct call stacks across the server/client boundary, and without it the error overlay reports the policy violation instead of the actual bug. React never uses `eval()` in a production build, so shipping the directive would weaken `script-src` for a feature that is not there. The `isDev` switch reads `NODE_ENV` (`:31`), which `next build` sets.

### What still holds

The directives that matter most for an authentication surface are all intact:

| Directive | Value | What it buys |
|---|---|---|
| `default-src` | `'self'` | everything not named below |
| `style-src` | `'self' 'unsafe-inline'` | Tailwind's runtime styles |
| `font-src` | `'self'` | self-hosted via `next/font`; no `fonts.googleapis.com` |
| `img-src` | `'self' data:` | the `data:` URI is the server-supplied two-factor QR code |
| `connect-src` | `'self'` + Turnstile + the API origin + `ws:`/`wss:` in dev | confines API calls |
| `frame-src` | `https://challenges.cloudflare.com` | what **we** may frame — the Turnstile widget |
| `frame-ancestors` | `'none'` | blocks clickjacking of the login and two-factor screens |
| `base-uri` | `'self'` | stops a `<base>` tag rewriting every relative URL |
| `form-action` | `'self'` | stops a form being pointed at another origin |

Plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin` (`:60-62`), and `poweredByHeader: false` (`next.config.mjs:137`).

`connect-src` is computed rather than hard-coded (`:33-57`). `'self'` alone is wrong the moment the backend is a separate origin, which it is in development — the app is served from `:3000` and calls `:8000`, so **every** fetch is blocked before it leaves the browser, and the symptom is a login screen that appears to do nothing. `apiOrigin` is derived from the same `NEXT_PUBLIC_API_BASE_URL` the client reads, so the two cannot disagree, and `:50-53` emits nothing unless the value parses to a real `http(s)` origin — an opaque origin would put a literal `null` into the directive, which allows nothing and reads like a bug.

Cloudflare Turnstile needs three directives, not one (`:73-80`): `script-src` for the challenge script, `frame-src` for the Cloudflare-served iframe, and `connect-src` because the widget's orchestration code fetches from that origin. No other third-party origin is allowed anywhere in the policy.

---

## The `/api` rewrite

`next.config.mjs:138-146` proxies `/api/:path*` to `${BACKEND_INTERNAL_URL}/api/:path*`. It looks like a convenience. It is the thing that keeps sessions alive in production.

### Why it exists

`next.config.mjs:99-124` records the reasoning:

The refresh token is an `httpOnly` cookie set `SameSite=Lax`. **Lax cookies are not sent on cross-*site* requests, and a platform subdomain is its own site.** `*.onrender.com` and `*.vercel.app` are both on the **Public Suffix List**, which means the browser treats `edubridge-web.onrender.com` and `edubridge-api.onrender.com` as two different sites, not two hosts of one site. Deployed as sibling subdomains, the frontend and backend are cross-site to the browser.

The failure mode that produces is the nastiest kind: **login succeeds**, the dashboard loads, and then `/api/auth/refresh` silently stops receiving the cookie. The user is signed out the moment the access token expires — roughly fifteen minutes in — **in production only**. Nothing in development reproduces it, because `localhost:3000` and `localhost:8000` are the same site.

Rewriting `/api/*` through the Next server makes the API **same-origin**. The Lax cookie keeps working with no backend change, `connect-src 'self'` already covers the calls, and there is no credentialed Cross-Origin Resource Sharing to configure. The cookie's `path=/api/auth/refresh` is unchanged by the rewrite, so it still matches.

### The trap

**Pointing `NEXT_PUBLIC_API_BASE_URL` at the backend's public address silently breaks refresh in production, and only in production.**

`lib/api/client.ts:25` reads that variable as the fetch prefix. Set it to `/api` and every call goes through the same-origin rewrite. Set it to `https://edubridge-api.onrender.com/api` — which looks more correct, is what the deployment dashboard invites, and works perfectly in every manual test that finishes inside one token lifetime — and every call is cross-site. Login still works. The dashboard still loads. Fifteen minutes later the user is signed out, and the reproduction requires waiting.

There are two variables and they are not interchangeable:

| Variable | Read by | Exposed to browser | Should be |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `lib/api/client.ts:25`, `next.config.mjs:46` | **Yes** | `/api` in any deployed environment |
| `BACKEND_INTERNAL_URL` | `next.config.mjs:132` | No | the backend's address, server-side only |

`:125-131` records a second failure this already caused: the value is pasted into a hosting dashboard by hand and a stray tab or newline rides along more often than not. Untrimmed, Next rejects the rewrite at **build** time with "`destination` does not start with `/`, `http://`, or `https://`" — accurate, but it reads like the URL is wrong when the URL is fine and the whitespace is invisible. Hence `.trim()` at `:132`.

Left unset, `:139` emits no rewrite at all.

Locally the rewrite exists in a dev build too, and is harmless either way: with the template's default `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api` the client calls `:8000` directly and never uses it, and both origins are `localhost` — same site — so Lax is satisfied regardless. Point the base URL at `/api` locally and the rewrite carries the calls instead, matching production.

---

## Testing

24 test files, run with `npm test` (Vitest). `npm run build` includes the TypeScript check.

The suite is not uniform — three files do something other than test a component:

| File | What it is |
|---|---|
| `lib/i18n-rules.test.ts` | A lint rule: fails on any physical Tailwind class in `app/` or `components/` |
| `lib/auth/navigation.test.ts` | The Role-Based Access Control regression net described above |
| `tailwind.config.test.ts` | Asserts the design tokens in the configuration match the design document |

The rest cover the transport client (`lib/api/client.test.ts`), the error envelope (`lib/api/errors.test.ts`), the middleware that routes every page (`proxy.test.ts`), the token and challenge stores (`lib/auth/tokenStore.test.ts`, `lib/auth/challenge.test.ts`), onboarding routing (`lib/auth/onboarding.test.ts`), locale routing (`i18n/routing.test.ts`), the guard (`components/app/SessionGuard.test.tsx`) and eight auth, signup, landing and layout components.

---

## Known defects

Recorded here rather than hidden until fixed, per the Phase 0 honesty rules. Numbering follows the 35-finding register in the Phase 0 plan.

### A6 — FIXED, phase 1b (2026-08-16)

`lib/auth/onboarding.ts:17` mapped `admin` to `/admin` and `lib/auth/navigation.ts` gave the admin
sidebar one entry pointing there, but `app/[locale]/(app)/` contained only `dashboard/`, `teacher/`
and `parent/`. Three call sites could send an administrator to that route — `SessionGuard.tsx:65`
(`routeForOnboardingState(state, 'admin')` when the state is `active`), `SessionGuard.tsx:69`
(`dashboardFor('admin')` on a role mismatch) and `TwoFactorChallenge.tsx:183` after a completed
challenge — and the result was a loop: the guard redirected, the route 404'd through the `(site)`
catch-all, and the guard's own fallback rendered "Redirecting…" for ever.

**`app/[locale]/(app)/admin/page.tsx` and `AdminDashboard` now exist.** The page is a shell, exactly
like the other three: no `/api/admin/*` endpoint is implemented, so its five cards name the five
FR-K1 duties — provisioning, curriculum currency, security posture, quotas, daily endpoint access
logs — and say plainly that each is not available yet.

**Why the test could not have caught it, and what changed.** `lib/auth/navigation.test.ts` had two
tests covering the nav table and neither covered the admin row: the *sends each role to its own
dashboard first* test omitted `admin` altogether, while *routes every non-dashboard item somewhere
that exists* allow-listed `admin` inside its regex alternation. The test written to catch this class
of regression had the regression written into it. Phase 1 added the missing first-item assertion.
Phase 1b added a third test that resolves every `coming-soon` href against the page's own
`generateStaticParams`, because a prefix regex accepts `/coming-soon/anything` and two of the four
new admin entries needed slugs that did not exist yet.

### The unlisted administrator login

Administrators do **not** sign in at `/login`. `POST /api/auth/login` refuses them, and
`POST /api/auth/admin/login` refuses everyone else — both with a 401 whose body is identical to a
wrong password, so neither endpoint can be used to work out which addresses are administrators
(prd.md FR-A2a).

`proxy.ts` is what makes the page unlisted. It was four lines wrapping next-intl; it now composes
three handlers, in order:

1. `pathname === '/' + process.env.ADMIN_LOGIN_PATH` → **rewrite** to `/en/admin-login`. A rewrite,
   not a redirect, so the address bar keeps the unlisted path and no locale prefix appears in it.
2. any path whose last segment is `admin-login` → **404**, so the ordinary route is not a second,
   listed door.
3. everything else → the existing next-intl middleware, untouched.

`ADMIN_LOGIN_PATH` carries **no `NEXT_PUBLIC_` prefix**, deliberately: that prefix would inline the
value into the browser bundle and publish it to every visitor. Measured on a production build, the
server chunk keeps the literal `process.env.ADMIN_LOGIN_PATH` read rather than folding it to a
constant, and the value appears **nowhere** under `.next/` — so it is read at runtime and never
enters a build artefact, client or server. Unset, the guard is `'' !== ''` and no rewrite happens:
the administrator login is simply unreachable, which is the correct failure.

> ⚠️ **The unlisted path is not an access control.** It keeps the entrance off the public site and
> nothing more. The endpoint's role check is the lock, and it holds whether or not the path is known.
> `proxy.test.ts` covers all three branches, including that ordinary locale routing is unchanged —
> that is the assertion worth having, because a middleware that stops calling next-intl takes down
> all 21 pages at once.

The page lives in the `(auth)` group rather than `(site)` because that group renders no top nav and
no footer: an operations door must not carry the marketing chrome. `AdminLoginForm` is a separate
component from `LoginForm` so the choice of endpoint is fixed at the route rather than behind a
prop a refactor could thread in from a URL; the challenge handoffs, the error mapping and the
captcha reset are imported, not copied. It deliberately offers no "create an account" link
(administrators are provisioned by SQL) and no "forgot password" link (that flow is public and
address-keyed, so linking it would confirm the address reaches a real reset e-mail).

### A7 — the backup-code download can silently produce no file

`components/auth/BackupCodes.tsx:41-51`:

```ts
const url = URL.createObjectURL(blob)
const link = document.createElement('a')
link.href = url
link.download = 'edubridge-backup-codes.txt'
link.click()                 // :49
URL.revokeObjectURL(url)     // :50 — synchronous, immediately after
```

Two problems in four lines. The anchor is **never appended to the document**, which several browsers require before a synthetic click on a download link does anything. And `URL.revokeObjectURL` is called **synchronously** on the next statement, which can invalidate the blob URL before the browser has started reading it.

The stakes are set by the component's own header (`:7-20`): the ten backup codes are shown **exactly once**. A user who clicks Download, sees nothing happen, and continues past the acknowledgement checkbox has lost their only recovery credential. The copy path (`:32-39`) reports its own failure through the `copied === 'failed'` banner at `:95-99`; the download path reports nothing, because a `click()` that does nothing throws nothing.

### A8 — sign-out no-ops on a network failure

`components/app/DashboardShell.tsx:45-48`:

```ts
async function signOut() {
  await logout()
  router.replace('/login')
}
```

No `try`/`catch`. `logout()` (`lib/api/endpoints.ts:179-188`) uses `try`/`finally`, not `try`/`catch` — the local session is dropped in the `finally` at `:186`, but the error still propagates. So on a network failure or a 500: `endSession()` runs, the access token is cleared, `await logout()` rejects, and `router.replace('/login')` at `:47` **never executes**.

The user is left looking at a dashboard that appears signed in, with no token behind it. Every subsequent request 401s. It looks like the sign-out button is broken, and it is — on the shared devices this product is used on, "sign out appeared to do nothing" is the worst possible failure for that button.

### C4 — CLOSED PERMANENTLY (phase 1b)

`.env.example` documented `NEXT_PUBLIC_API_MODE=mock` as the default, three lines below an
instruction to `cp .env.example .env.local`. Phase 1 flipped the value to `live`; **phase 1b then
deleted the entire mock layer along with the flag**, which is why this is closed rather than fixed.

The hazard was never the default on its own. It was that `API_MODE === 'mock'` was checked **before**
`NODE_ENV`, so the value copied forward into a deployment's environment would ship the in-memory
mock — seeded accounts and all — as the production backend, with nothing in the build warning,
because an explicitly set flag was exactly the condition the client treated as intentional.

`NEXT_PUBLIC_API_BASE_URL` is required in its place. See *Live data always* above.

### D5 — `VerifyEmail` reproduces the StrictMode deadlock `SessionGuard` documents fixing

`components/auth/VerifyEmail.tsx:41-73` uses precisely the pattern `SessionGuard.tsx:43-56` records as having deadlocked:

```ts
const attempted = useRef(false)                              // :41

useEffect(() => {
  if (token === null || attempted.current) return            // :44
  attempted.current = true                                   // :45

  let cancelled = false                                      // :47
  void (async () => {
    const result = await verifyEmail({ token })
    if (cancelled) return                                    // :51
    ...
  })()

  return () => { cancelled = true }                          // :70-72
}, [token])
```

A ref guard that survives React's development double-invoke, combined with a `cancelled` flag that discards the first response. React mounts, unmounts and remounts (`next.config.mjs:136`); the unmount sets `cancelled`, so the in-flight verification's result is thrown away at `:51`; the remount finds `attempted.current === true` and returns at `:44`, so no second request is made. `setState` is never called again and the screen stays on the `verifying` spinner (`:93-114`) permanently.

Development only, exactly like the original — which is what makes it costly. The `:29-31` comment explains the ref as a guard against a mail client prefetching the link and the human then clicking it. That is a real concern, but the token is single-use server-side, so the guard is defending against a duplicate request the server already rejects, at the price of a development-only deadlock.

### D6 — an unvalidated `onboarding_state` reaches `router.replace(undefined)`

`onboarding_state` is typed as a five-value union (`lib/api/types.ts:12-17`), but it arrives from the network and nothing validates it against that union at the boundary. Both lookup tables are plain `Record`s, so an unrecognised value returns `undefined`:

- `lib/auth/onboarding.ts:32` — `ONBOARDING_ROUTES[state]` → `undefined` → `SessionGuard.tsx:65` calls `router.replace(undefined)`
- `lib/auth/onboarding.ts:44` — `pendingOnboardingRoute` returns `undefined`, and the guard at `TwoFactorChallenge.tsx:176` is `if (next !== null)`. `undefined !== null` is **true**, so `:177` calls `router.replace(undefined)`.

Two of the three `pendingOnboardingRoute` call sites are accidentally safe — `VerifyEmail.tsx:61` and `TwoFactorEnrollment.tsx:136` both use `?? '/dashboard'`, and nullish coalescing catches `undefined` as well as `null`. `TwoFactorChallenge.tsx:176` uses an explicit `!== null` and is not.

The trigger is a backend that adds a sixth onboarding state, or renames one. Today the two sides agree; the register also notes that `onboarding_state` is a `Literal` on `MeResponse` and a plain string on four other backend responses (register **D13**), which is the drift channel.

### D17 — `error.tsx` logs the error object it refuses to render

`app/[locale]/error.tsx:16-18` states the security rule:

> The error is deliberately NOT shown. A stack or a message from a failed request can carry an email address, a token fragment or an internal path, and this page is reachable by anyone.

Then `:29-31`:

```ts
useEffect(() => {
  console.error(error)
}, [error])
```

The whole error object — message, stack and any attached properties — goes to the browser console. The console is not a private channel: it is readable by any extension with page access, captured by client-side error-reporting integrations, and visible to anyone who opens developer tools, including on a shared device. The page correctly renders only `error.digest` (`:63-67`), which is exactly the opaque, safe identifier that ought to be the *only* thing that leaves.

---

## Where the rest of the system is documented

This application makes no authorization decisions and holds no data. For anything below the transport layer:

- **[`../../backend/Architecture/architecture.md`](../../backend/Architecture/architecture.md)** — the layered request path, the two-layer authorization model and its current failure, the token kinds, the onboarding state machine as the server computes it, and the guardian gate.
- **[`../../backend/Architecture/database.md`](../../backend/Architecture/database.md)** — tables by domain, the complete Row-Level Security policy catalogue, the `app.*` privileged functions, and the invariants. **There is no database page in this folder**; this is it.
- **[`../../backend/Architecture/api-endpoints.md`](../../backend/Architecture/api-endpoints.md)** — implemented routes with `file:line`, and the specified-but-missing ones.
