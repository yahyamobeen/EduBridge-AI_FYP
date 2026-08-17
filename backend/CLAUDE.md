# CLAUDE.md — EduBridge AI backend

> Authoritative for `backend/`. When this file and [`/CLAUDE.md`](../CLAUDE.md) disagree, **this
> one wins** for backend work. Read [`/Claude/RULES.md`](../Claude/RULES.md) for the full rules and
> [`README.md`](README.md) for local setup.

Snapshot: **2026-08-15**.

---

## 1. What this is

FastAPI, SQLAlchemy **Core** (hand-written `text()` statements, not the ORM query layer),
PostgreSQL on Supabase. Authentication is **application-managed** — this service issues its own
JSON Web Tokens and hashes passwords with argon2id. Supabase Auth is deliberately unused, so
`app_user` holds `password_hash` itself.

**One router today**: `app/auth/routes.py`, 17 routes, all authentication, guardian or reference.
`tdd.md` §3.1 and §7.2 specify **48 endpoints — 31 do not exist.**
`app/workers/` is scaffolded with a `.gitkeep` and nothing else.

Full picture: [`Architecture/README.md`](Architecture/README.md).

## 2. The update mandate

> **Any change that adds, removes, renames or moves a route, model, migration, policy, privileged
> function, setting or dependency MUST update the matching document in
> [`Architecture/`](Architecture/) in the SAME change, and append to
> [`/Claude/HISTORY.md`](../Claude/HISTORY.md).**

The lookup table is [`/Claude/DOC-SYNC-MAP.md`](../Claude/DOC-SYNC-MAP.md). Short version:

| If you change… | Update… |
|---|---|
| `supabase/migrations/*` | `Architecture/database.md` **and** `database.html` |
| `app/auth/routes.py` | `Architecture/api-endpoints.md` |
| `app/auth/service.py`, `dependencies.py`, `tokens.py`, `gate.py`, `onboarding.py` | `Architecture/architecture.md` **and** `architecture.html` |
| `app/core/errors.py` | those, plus **`tdd.md` §7.3** and `frontend/lib/api/errors.ts` |

The pages cite `file:line`. If your edit shifts lines, re-verify the citations for the symbols you
moved.

## 3. Conventions that are load-bearing and non-obvious

Read these before writing code in the area. Each exists because the alternative broke something.

**The acting user is bound per transaction, and a stray `commit()` unbinds it.**
`set_current_user_id()` uses `set_config(..., is_local => true)`, which is transaction-scoped. A
`commit()` in the middle of a request ends that transaction and **silently discards the setting** —
every query after it returns zero rows with no error raised anywhere. If a query returns nothing
and the row is definitely there, look for a stray commit first.

**Bind first, read second.** `authenticated()` sets the user id and *then* reads `app_user`, so the
identity check itself runs **under** Row-Level Security rather than around it. Do not reorder.

**Pre-authentication paths use narrow `SECURITY DEFINER` functions, never the service connection.**
Login and refresh have no bound user, so an owner-scoped policy cannot be satisfied. The answer is
a function in schema `app` exposing exactly the columns that flow needs. **The standing rule: if a
new endpoint appears to need `get_service_db()`, add another narrow function rather than widening
the door.** No route in this codebase depends on the service session.

**`two_factor_pending` and `two_factor_enrollment` are separate token kinds on purpose.** Both were
once stored as `two_factor_pending`, which left `/2fa/verify` — the endpoint that exchanges a
pending token for a full session — unable to reject the longer-lived enrolment token. The kind is
the only thing that can enforce that boundary.

**The guardian gate fails closed in both directions.** An unknown class level is treated as
*gated*, because an unreadable `student_profile` row looks exactly like a forgotten binding, and
the point of the gate is not to serve a 14-year-old as though they were 18 because a read came back
empty. `gate.py` is deliberately free of database and settings imports so the decision is testable
without a connection string.

**`onboarding_state` is derived in one place and is not monotonic.** `onboarding.py` is the single
derivation; four endpoints once each rebuilt it inline and disagreed. Rule 4 can fire *after* a
user has been `active`, when a trial lapses — it is the only backward transition in the system, and
a consumer that caches `active` strands that user.

**No endpoint invents an error code.** The catalogue is `tdd.md` §7.3. `/2fa/resend` against a
TOTP enrolment answers `400 VALIDATION_ERROR` with `details.fields`, not a bespoke code — anything
outside the table reaches the client as an unrecognised string and renders as "something went
wrong".

**`INVALID_TOKEN` versus `TOKEN_EXPIRED` is not a coin toss.** A token that was already *used* is
`400 INVALID_TOKEN`. Only an **unused, lapsed** token is `410 TOKEN_EXPIRED`, which is what makes
the client offer a resend. Offering a resend for a spent token sends the user round a loop they
already completed.

**Registration, login and password reset must not reveal whether an address exists** — by body,
status code **or timing**. That is why `login()` verifies against a dummy argon2 hash on the
unknown-address branch, why the captcha runs *before* the lookup, and why outgoing mail is
dispatched off the request thread.

**Revocation writes commit before the exception is raised.** A lockout or a family revocation that
is written and not committed is undone by the very response that reports it, because the exception
unwinds through `get_db`, which rolls back. Both call sites commit deliberately, then raise.

## 4. Migrations

- **Never edit an applied migration.** Add a new one. Filenames are
  `YYYYMMDDHHMMSS_snake_case_subject.sql` and run in filename order. Latest applied:
  `20260803180000_login_2fa_lookup.sql`.
- **Changing a `RETURNS TABLE` or adding a parameter needs `DROP` then `CREATE`.** Adding a
  parameter *overloads* rather than replaces, and the existing call then matches both signatures
  and fails at runtime with "function name is not unique".
- **A `DROP FUNCTION` takes its `GRANT` and `COMMENT` with it.** Re-issue both.
- **Every file is idempotent.** The Supabase CLI (Command-Line Interface) does not wrap a file in a
  transaction, so a half-applied file must be re-runnable.
- Every `SECURITY DEFINER` function carries `SET search_path = public, pg_temp`,
  `REVOKE ALL … FROM PUBLIC`, `GRANT EXECUTE … TO app_backend`, and a `COMMENT ON FUNCTION` naming
  the calling endpoint first.
- **Claude never pushes a migration.** Produce the file, dry-run it, report the actual output. The
  repository owner applies it.

## 5. Testing

25 test files: **10 in `tests/unit`**, **15 in `tests/integration`**.

`tests/unit` must stay runnable with **no connection string, no engine and no live project** —
that is why `tests/conftest.py` has no fixtures and why `gate.py` and `onboarding.py` avoid
database imports. `tests/unit/conftest.py` sets environment variables **at import time**, because
`get_settings` is `lru_cache`d and a fixture runs too late. **A new required setting in
`config.py` breaks collection unless it carries a default or is added there.**

`tests/integration` needs a live database and has **no skip marker** — without `DATABASE_URL` and
`SERVICE_ROLE_DATABASE_URL` it errors at collection, which is not a test failure.

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit -q
```

`S105` (hardcoded password) is deliberately **not** globally ignored; silence it per line with a
reason after `--`.

## 6. Security invariants

- `DATABASE_URL` connects as **`app_backend`, never `postgres`.** The application refuses to start
  if its role reports `rolsuper` or `rolbypassrls`.
- `question_key` has **no Row-Level Security policy** and must never gain one.
- Chat content is **owner-only** — no teacher, parent or administrator read path.
- Secrets are never logged, never committed, never edited directly.

⚠️ **The database authorization layer does not currently hold.** `user-stories.md` card 1.5
promises the database catches a missed application check; an August 2026 audit found it would not
on most tables. The findings are recorded in
[`Architecture/database.md`](Architecture/database.md) — read that section before assuming a
policy protects you.
