# EduBridge AI Backend

Authentication and identity for the EduBridge AI platform: FastAPI, SQLAlchemy 2.0
against a SQL-first schema, application-managed JWT with argon2id, and PostgreSQL
Row Level Security.

See `../README.md` for the project overview, `../prd.md` and `../tdd.md` for the
source of truth.

## The one thing to understand first

Authentication is application-managed, so Supabase's `auth.uid()` does not exist.
Every RLS policy instead reads `app.current_user_id()`, which comes from a
transaction-scoped setting the application binds per request:

```sql
SELECT set_config('app.current_user_id', '<uuid>', true)
```

Three consequences that are easy to get wrong:

1. **Unset means zero rows, not an error.** That is the fail-closed default and
   it is deliberate. A query that mysteriously returns nothing is usually a
   missing binding, not a missing row.
2. **It dies with the transaction.** A `commit()` in the middle of a request
   discards it, and every query afterwards on that session silently returns
   nothing. Look for a stray commit first.
3. **The connection role matters more than the code.** `DATABASE_URL` must
   connect as `app_backend` (`NOBYPASSRLS`). As `postgres` every policy is inert
   while the application looks perfectly healthy — so the app now refuses to
   start if the role reports `rolsuper` or `rolbypassrls`.

## Environment

Copy the template and fill it in:

```bash
cp .env.example .env
```

| Variable | Notes |
|---|---|
| `DATABASE_URL` | **Must be `app_backend`.** Verified at startup. |
| `SERVICE_ROLE_DATABASE_URL` | Bypasses RLS. **Background jobs only** — no request path may use it. |
| `JWT_SECRET`, `JWT_REFRESH_SECRET` | At least 32 chars; `openssl rand -hex 32`. Rejected if left as the placeholder. |
| `APP_ENV` | `production` closes `/docs`, sets the cookie `secure` flag, and forbids a `*` CORS origin. |
| `CORS_ORIGINS` | Never `*`. With credentials enabled a wildcard makes Starlette echo the caller's origin, so any site could use a user's refresh cookie. |

## Pre-authentication is the interesting case

`login` and `refresh` run before there is a user to bind, so owner-scoped
policies cannot be satisfied. They do **not** use the service role for this.
Instead they call narrow `SECURITY DEFINER` functions
(`supabase/migrations/20260802140000_...`) that return only the columns those
flows need:

- `app.lookup_user_for_login(email)`
- `app.lookup_refresh_token(hash)`

If a new endpoint appears to need the service connection, add another narrow
function rather than widening the door.

## Running

Dependencies are managed with **uv** and pinned in `uv.lock` (tdd.md §2.2, §8.3).
There is no `requirements.txt` on purpose — a second manifest is a second thing
to drift.

```bash
uv sync --extra dev
```

```bash
uv run uvicorn app.main:app --reload
```

After changing a dependency in `pyproject.toml`, regenerate and commit the lock
**and both exports**, or they disagree with each other:

```bash
uv lock
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-hashes --no-emit-project --extra dev -o requirements-dev.txt
```

`requirements.txt` and `requirements-dev.txt` are pinned exports for pip users
and anything that cannot run uv. `uv.lock` remains the source of truth.

CI installs with `--frozen`, so it fails rather than silently resolving
something newer if the lockfile has drifted.

## Tests

```bash
uv run pytest tests/unit          # no database needed
```

```bash
uv run pytest tests/integration   # needs DATABASE_URL and SERVICE_ROLE_DATABASE_URL
```

Every integration test runs inside a transaction that is **rolled back**
(`tests/conftest.py`), so a run leaves no rows behind. That was not always true:
earlier runs wrote permanent `@test.com` users into the live project. If you add
a test that opens its own session, bind it to the fixture connection or it will
escape the rollback.

`tests/unit` deliberately holds the `onboarding_state` derivation, because the
single field the frontend routes on should be assertable without a database.

## What this module does not own

2FA enrolment and verification, email sending and password reset (Muneeb); RBAC
dependencies, the guardian invite/confirm flow and the Class 9-10 gate
(Mujtaba); the frontend (Yahya). `GET /subscription` and `POST
/subscription/select` are specified in `tdd.md` §7 and currently have **no
owner**.
