# CLAUDE.md — EduBridge AI

> **Read this first.** It governs how Claude, and any contributor, works in this repository.
> The most important rule: **when you change the code, you update the matching documentation in
> the same change.**

Snapshot: **2026-08-15**.

---

## 1. What this is

**EduBridge AI** is a curriculum-aligned AI tutor for Pakistani secondary students (Classes 9–12),
built as a Final Year Project at FCIT, University of the Punjab. Supervisor: Dr. Muhammad Arif
Butt.

It teaches against the **PCTB** and **STBB** board syllabi in English, Urdu and Roman Urdu. The
distinctive engineering contribution is not the tutor itself but the layer under it: **audited AI
skills and secure MCP (Model Context Protocol) servers**, with vetting, least-privilege manifests,
sandboxing and an agent software bill of materials.

**Four roles**: student, teacher, parent, administrator. **Access is paid** — one tier at
Rs. 999/month after a 14-day trial. Students in Classes 9 and 10 are minors and **cannot reach any
lesson until a parent confirms a guardian link**; Classes 11 and 12 may link optionally.

Authoritative product and design documents: [`prd.md`](prd.md), [`tdd.md`](tdd.md). The feature
inventory is [`user-stories.md`](user-stories.md) — 8 epics, 38 cards.

## 2. Repo map

```
EduBridge-AI_FYP/
├── CLAUDE.md              ← you are here (orientation + the rules)
├── Claude/                ← working docs
│   ├── RULES.md           ← full engineering and doc-maintenance rules
│   ├── DOC-SYNC-MAP.md    ← "if you touch X, update doc Y"
│   └── HISTORY.md         ← running changelog — append every change
├── backend/               ← FastAPI + SQLAlchemy Core. See backend/CLAUDE.md
│   └── Architecture/      ← architecture, database, api-endpoints
├── frontend/              ← Next.js App Router + React + TypeScript. See frontend/CLAUDE.md
│   └── Architecture/      ← architecture
├── supabase/migrations/   ← 11 applied SQL migrations. Never edit an applied one.
├── tools/                 ← the user-stories LaTeX generator and its checks
├── prd.md · tdd.md · user-stories.md · sprint-plan.md
├── ml/ · mcp-servers/ · infra/    ← scaffolded, no implementation (.gitkeep only)
└── render.yaml            ← Render blueprint for both services
```

**`backend/CLAUDE.md` and `frontend/CLAUDE.md` are authoritative for their own areas. When one of
them disagrees with this file, the application file wins.** This file is the cross-cutting layer.

## 3. How to work here — read before writing code

These four rules govern *how* changes are made. They bias toward caution over speed; for trivial
edits, use judgment.

### 3.1 Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, **stop**. Name what is confusing. Ask — one question at a time, never
  bundled.

This repository carries a lot of load-bearing, non-obvious convention. The answer to "why is it
done this weird way" is usually already written down in the `Architecture/` pages or in a code
comment, and reinventing it is a regression. Read the relevant section first.

### 3.2 Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

No features beyond what was asked. No abstractions for single-use code. No configurability nobody
requested. No error handling for impossible scenarios. If you write 200 lines and it could be 50,
rewrite it.

Concretely here: do **not** introduce `react-hook-form` or `zod` on the frontend (both are
installed and imported by zero source files — plain `useState` is the convention), do not add an
ORM query layer over the hand-written `text()` statements, and do not add a background-job
framework for a single scheduled `DELETE`.

### 3.3 Surgical changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, **mention it — don't delete it**.
- Remove imports and variables that **your** change orphaned. Leave pre-existing dead code alone.

The test: every changed line traces directly to the request.

**The carve-out that makes this workable:** *never change a working feature **as a side effect** of
unrelated work.* Changing a feature that is itself the subject of a defect **is** the work — that
is not a violation of this rule.

### 3.4 Goal-driven execution

State a brief plan up front, then verify each step:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

**Verification here IS tests — this repository has them.** 25 backend test files (10 in
`backend/tests/unit`, 15 in `backend/tests/integration`) and 22 frontend test files. Report the
real result before saying done; never "should pass".

| Change touches | Verify with |
|---|---|
| Backend logic | `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest tests/unit -q` |
| Backend + database | the above plus `uv run pytest tests/integration -q` |
| Frontend | `npm test` · `npm run build` (the build includes the TypeScript check) |
| Migration | dry run against a shadow or branch database, then the integration suite |
| Full stack | all of the above, then exercise the feature by hand in the production build |

`tests/integration` needs a live database (`DATABASE_URL` and `SERVICE_ROLE_DATABASE_URL`). There
is **no skip marker** — without them the suite errors at collection, which is not a test failure.

## 4. The update mandate (non-negotiable)

The `Architecture/` pages cite **`file:line`**. They go stale the instant code moves.

> **Any change that adds, removes, renames or moves a route, model, migration, policy, privileged
> function, setting or dependency MUST update the matching architecture document in the SAME
> change, and append a line to [`Claude/HISTORY.md`](Claude/HISTORY.md).**

Which document to touch is in [`Claude/DOC-SYNC-MAP.md`](Claude/DOC-SYNC-MAP.md).

**Line numbers matter.** If your edit shifts lines in a referenced file, re-verify the citations for
the symbols you moved. Approximate is fine for untouched symbols; never knowingly leave a wrong
line number.

## 5. `prd.md` and `tdd.md` are the contract

Ground every decision in `prd.md`, `tdd.md`, the applied SQL in `supabase/migrations/`, existing
repository code, or official library documentation — and **say which**. Never invent an endpoint,
column, config key, error code or requirement.

**If work requires something not in those two documents, update both in the same change**, along
with the architecture pages. Never build ahead of the contract silently. If sources conflict,
surface the conflict and ask — never resolve it quietly.

## 6. Current state, honestly

| | |
|---|---|
| Backend | **18 routes, all authentication or reference.** One router (`app/auth/routes.py`). `tdd.md` specifies **49 endpoints — 31 do not exist.** Phase 1b added `POST /auth/admin/login` to both sides of that ledger at once. |
| Frontend | 20 pages, 3 route groups, 3 locales. Auth and onboarding journeys complete. |
| Database | 11 applied migrations, 33 `app.*` functions, 73 Row-Level Security policies. |
| `ml/`, `mcp-servers/`, `infra/`, `backend/app/workers/` | **Scaffolded, no implementation** — `.gitkeep` placeholders only. |

Against the 38 user-story cards: **Epic 1 (identity, authentication, consent) is roughly 80%
built. Epics 2 and 4–8 have no backend at all** — including the whole tutor and the secure-skills
layer the proposal calls the distinctive contribution.

⚠️ **A review of Epic 1 in August 2026 produced 35 findings, ten of them reachable through the API
today.** The most important structural one: `user-stories.md` card 1.5 promises every request is
checked by the application **and again by the database**, and the Row-Level Security audit shows
the database would **not** catch a missed check on most tables. The application layer is currently
holding alone. The full register and its remediation plan live outside this repository; the
database-layer findings are recorded in
[`backend/Architecture/database.md`](backend/Architecture/database.md).

## 7. Commands

```bash
cd backend && uv sync --extra dev
```

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit -q
```

```bash
cd frontend && npm ci && npm test && npm run build
```

Backend runs with `uvicorn app.main:app --reload`; the frontend with `npm run dev`. The application
**refuses to start** if its database role can bypass Row-Level Security — that is deliberate, not a
bug.

## 8. Git

**Claude never commits, never creates a branch, never opens a pull request and never pushes.**
Supply a commit message; the repository owner performs every Git operation. Commit messages carry
**no `Co-Authored-By` line and no tool attribution**, and describe the final state of a phase rather
than the intermediate fixes.

**Migrations are never pushed by Claude.** Produce the file, verify it with a dry run, report the
actual output. The repository owner applies it before a merge to `main`.

Full rules: [`Claude/RULES.md`](Claude/RULES.md).
