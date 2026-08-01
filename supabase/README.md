# Database (Supabase / PostgreSQL)

Schema for EduBridge AI's user and application data, as versioned SQL migrations.

Implements [`../tdd.md`](../tdd.md) §5 and [`../prd.md`](../prd.md) §9.

## Migrations

| File | Contents |
|---|---|
| `20260801120000_initial_schema.sql` | Extensions, enums, all tables, indexes, triggers, partitions |
| `20260801120100_rls_policies.sql` | `app_backend` role, RLS helper functions, Row Level Security policies |
| `20260801120200_seed_reference_data.sql` | Boards, class levels, subjects (48 tracks) |

Migrations run in filename order. **Never edit an applied migration** — add a new one instead.

## Scope

**Included:** identity & RBAC · curriculum taxonomy · classroom & spaces · assessment · learner analytics · tutor sessions · security & platform logs

**Deferred to the chatbot layer:** knowledge-base content (`kb_document`, `curriculum_item`, `textbook_figure`, `urdu_note_item`, `glossary_term`) and the vector store.

## Design decisions

- **Auth is application-managed.** FastAPI issues its own JWTs and hashes passwords with argon2id. Supabase Auth (`auth.users`) is deliberately not used, so `app_user` holds `password_hash` itself.
- **RLS is defense-in-depth.** The frontend never talks to Supabase directly — FastAPI is the only client — but RLS is enabled and *forced* so a leaked key or an application bug still cannot expose one student's data to another.
- **Answer keys are isolated.** `question_key` is a separate table with **no RLS policy at all**, so `app_backend` can never read it. Grading runs under a service role. This is the database-level backstop for NFR-8.
- **Chat is owner-only.** No teacher, parent, or admin read path exists for `chat_session` / `message` / `visual_aid` — a minor's chat is private (PRD §21 TEL-3).
- **SLOs are soft-retired**, never deleted, so historical mastery keeps its meaning across curriculum years.

## Setup

Install the Supabase CLI once:

```bash
npm install -g supabase
```

Link this repo to your Supabase project (get the ref from your project URL):

```bash
supabase link --project-ref <your-project-ref>
```

Apply all migrations:

```bash
supabase db push
```

## Required manual step — backend role password

The migration creates the `app_backend` role with `NOLOGIN` and no password, because **passwords must never be committed**. Set it once in the Supabase SQL Editor:

```sql
ALTER ROLE app_backend WITH LOGIN PASSWORD 'your-strong-password';
```

Then point `DATABASE_URL` in `backend/.env` at that role — *not* at `postgres`. Connecting as `postgres` bypasses RLS and defeats the whole policy layer.

## How FastAPI must connect

RLS policies read the current user from a session variable. Every request transaction must set it:

```python
async with engine.begin() as conn:
    await conn.execute(
        text("SET LOCAL app.current_user_id = :uid"),
        {"uid": str(current_user.id)},
    )
    # ... queries here are automatically filtered by RLS
```

`SET LOCAL` is transaction-scoped, which is what makes this safe under connection pooling. If the variable is not set, `app.current_user_id()` returns `NULL` and policies deny access — fail-closed by design.

Background jobs that legitimately need unrestricted access (OLAP ETL, quiz auto-submit sweeper, vector reconciliation) connect as the owner/service role instead.

## Creating a new migration

```bash
supabase migration new add_something_useful
```

Write plain SQL in the generated file, commit it, and open a PR.

## Notes

- `gen_random_uuid()` (UUIDv4) is used for primary keys. On PostgreSQL 18+ you may switch to `uuidv7()` for time-ordered keys and better index locality.
- `audit_log` and `api_request_log` are range-partitioned by `created_at` with a `DEFAULT` partition so inserts never fail. Add monthly/daily partitions and a retention job before production traffic.
