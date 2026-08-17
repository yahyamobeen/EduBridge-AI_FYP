# EduBridge AI Frontend — Architecture Docs

Living documentation for the EduBridge AI **Next.js** frontend. **These docs cite `file:line` and must be kept in sync with the code** — see [`/CLAUDE.md`](../../CLAUDE.md), [`frontend/CLAUDE.md`](../CLAUDE.md) and [`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md).

> **This is the first documentation this application has had.** Before it, everything below had to be reconstructed from source — which is finding **E4** in the Phase 0 register.

> Snapshot date: **2026-08-15**. Describes commit `eea0e74` on branch `fix-epic-1`, plus the uncommitted Phase 0 documentation itself.
> The `.html` file renders its diagrams with [Mermaid](https://mermaid.js.org/) from a **vendored local copy** at `assets/mermaid.min.js` — it renders with the network disabled, which is the point: this project is demonstrated in a viva room. It shares the same visual shell as the backend docs.

## The docs

| Doc | What it covers |
|---|---|
| [architecture.md](architecture.md) / [architecture.html](architecture.html) | The three route groups, the layout tree, `SessionGuard`, `onboarding_state` routing, `navigation.ts` as a Role-Based Access Control boundary, the API (Application Programming Interface) client, credential storage, internationalisation, the Content Security Policy deviation, and the `/api` rewrite. Start here — it is the only page. |

## Why this is lighter than the backend

This application is **screens and a transport client**. Every authorization decision, every piece of business logic and the entire data model live in the **backend**. There is no database page here, and no separate endpoint catalogue, because neither belongs to this repository half:

- The data model, the Row-Level Security policy catalogue and the `app.*` privileged functions → [`../../backend/Architecture/database.md`](../../backend/Architecture/database.md)
- The endpoints this application calls, and the 31 specified-but-missing ones → [`../../backend/Architecture/api-endpoints.md`](../../backend/Architecture/api-endpoints.md)
- The request lifecycle, the token kinds and the onboarding state machine as the **server** computes it → [`../../backend/Architecture/architecture.md`](../../backend/Architecture/architecture.md)

The single most load-bearing sentence in this whole folder follows from that split: **`SessionGuard` is not a security control.** It decides what a signed-in person is *shown*. What they may *do* is decided by the API layer and by Row-Level Security in PostgreSQL. A reader who takes the guard for the gate will draw the wrong conclusion about this system's security posture — and the backend documents record that the second of those two layers does not currently hold (register section **B**).

## At a glance

- **Next.js 16 + React 19**, App Router, TypeScript, Tailwind CSS v3.
- **22 pages** across **3 route groups** — `(site)`, `(auth)`, `(app)` — all under one `[locale]` segment.
- **3 locales**: `en`, `ur`, `ur-Latn`, each with **429** leaf message keys, in identical order. `ur` is the only right-to-left locale.
- **24 test files** (Vitest), including a lint-style test that fails the build on a physical Tailwind class, and a regression guard on `proxy.ts` — the file that routes every page.
- Access token in **memory only**; refresh token in an `httpOnly` cookie JavaScript cannot read.
- One transport client with proactive refresh, single-flight refresh, and an error-code allow-list for retry.
- **No mock layer.** It was deleted in phase 1b; `NEXT_PUBLIC_API_BASE_URL` is required and a backend must be running.

### How those numbers were measured

Run from `frontend/`:

```bash
find app -name "page.tsx" | wc -l                                   # 22
find app -type d -name "(*)" | wc -l                                # 3
find . -path ./node_modules -prune -o -path ./.next -prune -o \
     \( -name "*.test.ts" -o -name "*.test.tsx" \) -print | wc -l   # 24
ls messages/                                                        # en.json  ur-Latn.json  ur.json
node -e "const f=require('fs');const c=o=>Object.values(o).reduce((n,v)=>n+(v&&typeof v==='object'?c(v):1),0);for(const l of ['en','ur','ur-Latn'])console.log(l,c(JSON.parse(f.readFileSync('messages/'+l+'.json','utf8'))))"
                                                                    # en 429 / ur 429 / ur-Latn 429
```

The test-file count is confirmed independently by the runner: `npm test` reports **`Test Files  24 passed (24)` · `Tests  283 passed (283)`** at this snapshot.

## Known defects, recorded rather than hidden

Seven findings from the Epic 1 review land in this application. They are documented in [architecture.md](architecture.md#known-defects) with their exact locations rather than left until fixed:

| # | Summary | Status |
|---|---|---|
| A6 | The `admin` role routes to `/admin`, which does not exist — and a test allow-lists it | **Fixed** (Phase 1b) — `app/[locale]/(app)/admin/page.tsx` and `AdminDashboard` exist, and administrators now sign in at a separate endpoint reached through an unlisted path. Two nav tests covered the admin row between them and neither actually did: the first-item test omitted `admin`, the href test allow-listed it. Phase 1 added the missing assertion; Phase 1b added a third that resolves every coming-soon href against the page's own `generateStaticParams` |
| A7 | Backup-code download can silently produce no file | **Fixed** (Phase 1) — the anchor is appended before the click and removed after, `revokeObjectURL` is deferred rather than run on the same tick, and a failure now renders `downloadFailed` in all three locales. Two bugs in four lines, on codes shown exactly once with no way back and no regenerate endpoint |
| A8 | Sign-out no-ops on a network failure | **Fixed** (Phase 1) — `signOut` wraps `logout()` in `try`/`catch` with the redirect in `finally`. `logout()` clears the session and then **re-throws by design**, so the redirect must not depend on it resolving |
| C4 | `.env.example` ships `NEXT_PUBLIC_API_MODE=mock` as the documented default | **Closed permanently** (Phase 1b) — Phase 1 flipped the template to `live`; Phase 1b then deleted the entire mock layer, ~950 lines, along with the flag. The hazard is now structural rather than a matter of configuration: there is no mock to select. `NEXT_PUBLIC_API_BASE_URL` is required in its place |
| D18 | `login` never sends the email code, so an `email_otp` account lands on a screen that claims one was sent — and the control that sends it had **no message keys in any locale**, rendering as `auth.twoFactor.resend` | **Half fixed** (Phase 1b) — the three keys now exist in all three locales and `TwoFactorChallenge.test.tsx` gained the `onError` sweep that would have caught it. The auto-send is deferred to Phase 5, where it belongs beside D1 |
| D5 | `VerifyEmail` reproduces the StrictMode deadlock `SessionGuard` documents fixing |
| D6 | An unvalidated `onboarding_state` reaches `router.replace(undefined)` |
| D17 | `error.tsx` logs the error object it refuses to render |

## Commands

Run from `frontend/`:

```bash
npm test          # Vitest, 24 files
npm run build     # includes the TypeScript check
npm run lint      # ESLint
npm run typecheck # tsc --noEmit
```

## Keeping these current

When you change the code, update this page in the same change and append to [`/Claude/HISTORY.md`](../../Claude/HISTORY.md). The mapping of *code area → document* is in [`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md); `app/**`, `lib/api/*` and `lib/auth/*` all map here. **The types in `lib/api/types.ts` are a contract with the backend** — a change there is a change in both repositories' documents.
