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
- **20 pages** across **3 route groups** — `(site)`, `(auth)`, `(app)` — all under one `[locale]` segment.
- **3 locales**: `en`, `ur`, `ur-Latn`, each with **398** leaf message keys. `ur` is the only right-to-left locale.
- **22 test files** (Vitest), including a lint-style test that fails the build on a physical Tailwind class.
- Access token in **memory only**; refresh token in an `httpOnly` cookie JavaScript cannot read.
- One transport client with proactive refresh, single-flight refresh, and an error-code allow-list for retry.
- A **mock backend** compiled into development builds and dead-code-eliminated out of live ones.

### How those numbers were measured

Run from `frontend/`:

```bash
find app -name "page.tsx" | wc -l                                   # 20
find app -type d -name "(*)" | wc -l                                # 3
find . -path ./node_modules -prune -o -path ./.next -prune -o \
     \( -name "*.test.ts" -o -name "*.test.tsx" \) -print | wc -l   # 22
ls messages/                                                        # en.json  ur-Latn.json  ur.json
node -e "const f=require('fs');const c=o=>Object.values(o).reduce((n,v)=>n+(v&&typeof v==='object'?c(v):1),0);for(const l of ['en','ur','ur-Latn'])console.log(l,c(JSON.parse(f.readFileSync('messages/'+l+'.json','utf8'))))"
                                                                    # en 398 / ur 398 / ur-Latn 398
```

The test-file count is confirmed independently by the runner: `npm test` reports **`Test Files  22 passed (22)` · `Tests  263 passed (263)`** at this snapshot.

## Known defects, recorded rather than hidden

Seven findings from the Epic 1 review land in this application. They are documented in [architecture.md](architecture.md#known-defects) with their exact locations rather than left until fixed:

| # | Summary |
|---|---|
| A6 | The `admin` role routes to `/admin`, which does not exist — and a test allow-lists it |
| A7 | Backup-code download can silently produce no file |
| A8 | Sign-out no-ops on a network failure |
| C4 | `.env.example` ships `NEXT_PUBLIC_API_MODE=mock` as the documented default |
| D5 | `VerifyEmail` reproduces the StrictMode deadlock `SessionGuard` documents fixing |
| D6 | An unvalidated `onboarding_state` reaches `router.replace(undefined)` |
| D17 | `error.tsx` logs the error object it refuses to render |

## Commands

Run from `frontend/`:

```bash
npm test          # Vitest, 22 files
npm run build     # includes the TypeScript check
npm run lint      # ESLint
npm run typecheck # tsc --noEmit
```

## Keeping these current

When you change the code, update this page in the same change and append to [`/Claude/HISTORY.md`](../../Claude/HISTORY.md). The mapping of *code area → document* is in [`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md); `app/**`, `lib/api/*` and `lib/auth/*` all map here. **The types in `lib/api/types.ts` are a contract with the backend** — a change there is a change in both repositories' documents.
