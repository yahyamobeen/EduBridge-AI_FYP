# Backend architecture documentation

> The EduBridge AI backend as it actually is — not as the requirements describe it.
>
> **Snapshot: 2026-08-15 · commit `eea0e74`.**

EduBridge AI is a Final Year Project at the Faculty of Computing and Information Technology,
University of the Punjab: an Urdu-and-English study companion for Punjab and Sindh board students in
Classes 9–12, with four roles — student, teacher, parent, administrator — and a paid single tier at
Rs. 999/month behind a 14-day trial.

These pages exist because **everything here would otherwise have to be reconstructed from source**,
by the next contributor and again at the viva. They record the system that is built, the system that
is specified but missing, and the defects found in review — all three, kept distinct.

---

## The documents

| Document | What it covers |
|---|---|
| **[`architecture.md`](architecture.md)** · [HTML](architecture.html) | The layers and the request lifecycle; the two-layer authorization model **and its current failure**; the privileged-function escape hatch and the rule for extending it; the seven token kinds; the onboarding state machine and why it is not monotonic; the guardian gate; configuration and deployment. |
| **[`database.md`](database.md)** · [HTML](database.html) | **The highest-value page here.** Every table by domain with `file:line`; the **complete Row-Level Security policy catalogue** — all 73 policies with verb, role, `USING` and `WITH CHECK` — which exists nowhere else and cannot be reconstructed quickly from eleven migrations; the 33 `app.*` privileged functions with signature, volatility, return, grant and calling endpoint; the invariants with the reason for each; findings B1–B19; and the migration rules. |
| **[`api-endpoints.md`](api-endpoints.md)** | Every implemented route with `file:line`, request and response shape and error codes — **and the 31 specified-but-missing ones**, which makes it the honest build-state record as well as the interface reference. |

The `.md` and `.html` files are **parallel documents, not generated from each other**. The Markdown
reads anywhere — a terminal, a diff, a code review. The HTML carries the clustered
entity-relationship diagrams, one per domain, and renders offline from a locally vendored Mermaid
(see [`assets/README.md`](assets/README.md)).

There is no separate frontend database page. The frontend documentation
(`frontend/Architecture/`) points here, because there is one database and one description of it.

---

## System at a glance

Every number below was measured, and the command that produced it is recorded next to it. Run these
from the repository root; if a number no longer matches, the documents are stale and it is the
documents that are wrong.

| Measure | Value | Command |
|---|---|---|
| HTTP endpoints implemented | **17 of 48 specified** | `grep -cE '^@router\.' backend/app/auth/routes.py` (plus `/health` in `backend/app/main.py`) |
| Applied database migrations | **11** | `ls supabase/migrations/*.sql \| wc -l` |
| Live Row-Level Security policies | **73** | see [the reconciliation in `database.md`](database.md#why-73-73-and-72-are-all-correct) |
| Live `app.*` privileged functions | **33** | 34 defined, one dropped — `grep -nE 'DROP FUNCTION' supabase/migrations/*.sql` |
| …of which `SECURITY DEFINER` | **35 of 37 definitions** | `grep -hE '^[^-]*SECURITY DEFINER' supabase/migrations/*.sql \| wc -l` |
| Base tables | **46** (+2 default partitions, +1 view) | `grep -hE '^CREATE TABLE' supabase/migrations/*.sql \| wc -l` minus the 2 `PARTITION OF` rows |
| Enumerated types | **22** | `grep -hE '^CREATE TYPE' supabase/migrations/*.sql \| wc -l` |
| Backend test files | **25** (pytest — `tests/unit`, `tests/integration`) | `find backend/tests -name 'test_*.py' \| wc -l` |
| Frontend test files | **22** (Vitest) | `find frontend -path frontend/node_modules -prune -o -name '*.test.ts' -print -o -name '*.test.tsx' -print \| wc -l` |
| Findings from the Epic 1 review | **35**, all recorded, none hidden | 10 live through the API, 19 database defence-in-depth, 5 latent, 17 correctness, 6 gaps |

**Scaffolded, not empty.** `ml/`, `mcp-servers/`, `infra/` and `backend/app/workers/` contain
**`.gitkeep` files only** (`mcp-servers/` and `infra/` additionally carry a `.env.example`). No code
lives in them yet — `find ml mcp-servers infra backend/app/workers -type f`.

### Repository map

| Path | What it is |
|---|---|
| `backend/` | FastAPI application — `app/auth/` (routes, service, tokens, gate, onboarding), `app/core/` (config, database, errors, rate limiting), `app/models/` |
| `frontend/` | Next.js App Router application |
| `supabase/migrations/` | The 11 versioned SQL migrations — the schema's source of truth |
| `tools/` | Build scripts for the User Stories deliverable |
| `docs/` | Five point-in-time plan files; **not** a description of the system as it stands — that is what these pages are for |
| `prd.md`, `tdd.md` | The contract. Work requiring something not in them updates both in the same change |

---

## The single most important thing recorded here

User-story card 1.5 promises that each request is *"checked by the application and again by the
database, so that a single missed check can never expose another student's data."*

**That is false today.** The database sweep found that most write policies are `FOR ALL` with
ownership as the only predicate; grants are table-wide, so Row-Level Security gives no column
protection anywhere; roughly ten privileged functions accept a user identifier without checking it
belongs to the caller; and one view bypasses Row-Level Security entirely. **The application layer is
holding alone.**

These are **defence-in-depth failures, not remote exploits.** Reaching any of them requires the
ability to run arbitrary SQL as `app_backend`, and every implemented route is narrow — each issues
fixed statements with bound parameters, and no current route passes a request-controlled user
identifier into a privileged function. But several go live the moment a matching endpoint ships,
which is the argument for fixing them before the endpoints arrive.

The full catalogue is [`database.md` § Known gaps](database.md#known-gaps). Fixes are Phase 2.

---

## Three questions these pages should answer without opening the code

If a reader cannot answer these from the documents alone, the documents have failed.

**1. Which endpoints exist?**
Seventeen, all in `backend/app/auth/routes.py`, plus `/health`. Registration, login, refresh,
logout, `/auth/me`, `/reference/enums`, four two-factor routes, two email routes, two password
routes, and three guardian routes. The full list with `file:line`, and the 31 that are specified but
not built, is in [`api-endpoints.md`](api-endpoints.md).

**2. What happens on a wrong two-factor code?**
`_record_2fa_failure` (`backend/app/auth/service.py:657`) calls
`app.verify_2fa_failure(uuid, smallint, timestamptz)` to persist the incremented failure count and
any lockout, writes a `2fa_verify_failed` row to `audit_log`, and **commits immediately** — the
commit is the whole point, because the caller raises straight afterwards and that exception would
otherwise unwind through `get_db` and roll the lockout back, giving an attacker unlimited attempts
while the code looked correct. The lockout duration comes from an escalating threshold ladder
(`_lockout_after`, `service.py:643`); the highest threshold met wins. **Only a successful
verification clears the counters** — `app.verify_2fa_success` — so re-enrolling cannot launder a
lockout, which is why `app.upsert_2fa_enrollment` was changed to stop resetting them
(`supabase/migrations/20260803160000_2fa_lockout_and_email_locale.sql:8-13`). The eleven functions
behind these flows are listed in
[`database.md` § The `app.*` privileged functions](database.md#the-app-privileged-functions).

**3. Why does `question_key` have no policy?**
Because that is what makes answer keys unreadable. Row-Level Security is **enabled and forced** on
the table, and no policy was ever written for it — and under forced Row-Level Security, a table with
no matching policy is deny-all. So `app_backend` cannot read a single row: no route, no serializer,
no accidental `SELECT *` can leak an answer key, because the database refuses before the application
is even consulted. Grading runs under the service role. This is the database-level backstop for
non-functional requirement NFR-8, *"answer keys never leave the server"*
(`supabase/migrations/20260801120100_rls_policies.sql:327-332`). **It must never gain a policy** —
a later migration fixing six *other* policy-less tables repeats the warning explicitly:
*"Do not 'fix' it here."* See
[`database.md` § Invariants](database.md#invariants-and-the-reason-for-each).

---

## How these documents are written

Four rules, so that a reader knows what they are holding:

* **Every count is measured, with the command recorded next to it.** A number without a command is
  not a measurement.
* **Every `file:line` is real** and resolves to the symbol named. Where a migration was later
  superseded, the citation points at the *live* definition, with the original noted.
* **"Specified but missing" is kept distinct from "implemented."** Scaffolded directories are named
  as scaffolded, never as done and never as empty.
* **Known defects are recorded, not omitted until fixed.** Every one carries its finding number and
  its location.

---

## Keeping these current

The update mandate in [`/CLAUDE.md`](../../CLAUDE.md): **any change that adds, removes, renames or
moves a route, model, migration, policy, privileged function, setting or dependency must update the
matching architecture document in the same change**, and append one line to
[`/Claude/HISTORY.md`](../../Claude/HISTORY.md):

```
- YYYY-MM-DD — <what changed> — docs updated: <files> — <handle>
```

Which document to update is a lookup, not a judgement call —
[`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md) maps code areas to documents. The entries
that land here:

| Code area | Update |
|---|---|
| `supabase/migrations/*` | [`database.md`](database.md) + [`database.html`](database.html) |
| `backend/app/auth/routes.py` | [`api-endpoints.md`](api-endpoints.md) |
| `backend/app/auth/{service,dependencies,tokens,gate,onboarding}.py` | [`architecture.md`](architecture.md) + [`architecture.html`](architecture.html) |
| `backend/app/core/config.py`, `render.yaml` | the deployment section of [`architecture.md`](architecture.md) |
| anything touching a requirement | `prd.md` **and** `tdd.md`, in the same change |

When you update, re-run the commands in [System at a glance](#system-at-a-glance) and change the
numbers, the snapshot date and the commit at the top of every page you touched. A page whose counts
no longer reproduce is worse than no page, because it is believed.

## Verifying a change

| Change touches | Verify with |
|---|---|
| Backend logic | `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest tests/unit -q` |
| Backend + database | the above plus `uv run pytest tests/integration -q` (needs a live database; there is no skip marker, so it errors at collection without one) |
| Frontend | `npm test` · `npm run build` (which includes the TypeScript check) |
| Migration | dry run against a shadow or branch database, then the integration suite |
| Full stack | all of the above, then exercise the feature by hand in the production build |

**The agent never commits, never branches, never pushes, and never applies a migration.** It supplies
a commit message and the verified migration file; the repository owner performs every Git and
database operation.
