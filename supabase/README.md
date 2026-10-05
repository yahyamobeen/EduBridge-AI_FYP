# Database (Supabase / PostgreSQL)

Schema for EduBridge AI's user and application data, as versioned SQL migrations.

Implements [`../tdd.md`](../tdd.md) §5 and [`../prd.md`](../prd.md) §9.

> **This file is the operator's guide: what the migrations are, how to apply them, how to write a
> new one.** The *description* of the schema — every table by domain, the complete Row-Level
> Security policy catalogue, the `app.*` privileged functions, the invariants and the known gaps —
> lives in **[`../backend/Architecture/database.md`](../backend/Architecture/database.md)**
> (diagrams: [`database.html`](../backend/Architecture/database.html)). Keep design detail there,
> not here, so the two cannot drift apart.

## Migrations

**32 applied** (`ls supabase/migrations/*.sql | wc -l`, 2026-10-05). The seven classroom files from
`20261004120000` on were dry-run on a shadow database first, then applied by the owner with
`supabase db push` — four on 2026-10-04, `20261004150000`, `20261005120000` and `20261005130000` on
2026-10-05 — and re-verified on the live database.

| # | File | Contents |
|---|---|---|
| 1 | `20260801120000_initial_schema.sql` | Extensions (`citext`, `pg_trgm`), the `app` schema, 20 enumerated types, 43 tables plus 2 default partitions, the `two_factor_status_v` admin view, 38 indexes, 7 `updated_at` triggers |
| 2 | `20260801120100_rls_policies.sql` | The `app_backend` role and its grants, 6 Row-Level Security helper functions, the blanket `ENABLE`/`FORCE` loop, and 58 `CREATE POLICY` statements |
| 3 | `20260801120200_seed_reference_data.sql` | Boards, class levels, subjects and elective-group mappings. Idempotent |
| 4 | `20260802120000_subscriptions_and_oauth.sql` | `subscription_plan`, `subscription`, `oauth_identity`; the Rs. 999/month plan row; 5 policies |
| 5 | `20260802140000_reference_read_and_auth_lookups.sql` | Read policies for the six curriculum tables (which were deny-all), the missing `FORCE` on the three subscription tables, and the first 5 pre-authentication `SECURITY DEFINER` lookups |
| 6 | `20260802140100_token_kind_enrollment.sql` | Adds `two_factor_enrollment` to the `token_kind` enum. **Its own file**, because PostgreSQL will not let a value added by `ALTER TYPE … ADD VALUE` be used in the same transaction |
| 7 | `20260802150000_guardian_gate_and_partition_rls.sql` | Row-Level Security on the two **default partitions** (they had none), the owner-scoped `app_user_insert`, and 3 guardian-flow functions |
| 8 | `20260803090000_guardian_link_write_boundary.sql` | Closes the guardian forgery hole: a link is born `pending`, no direct UPDATE may produce `verified`, and the re-invite reset moves into `app.reinvite_guardian_link` |
| 9 | `20260803120000_2fa_email_password_lookups.sql` | 16 `SECURITY DEFINER` functions for the eight pre-session endpoints (two-factor, email verification, password reset) |
| 10 | `20260803160000_2fa_lockout_and_email_locale.sql` | Corrective: re-enrolling can no longer launder a lockout; activation records the consumed TOTP counter; `check_token_status` returns `revoked`; adds `lookup_user_for_email_flow`; drops the duplicate `issue_token_for_email` |
| 11 | `20260803180000_login_2fa_lookup.sql` | `app.lookup_2fa_for_login` — login read `two_factor_enrollment` with a plain `SELECT` before a session existed, got zero rows under Row-Level Security, and read that as "not enrolled" |
| 12 | `20260816120000_block_admin_self_registration.sql` | **Phase 1** (A1). `app_user_insert` gains `role <> 'admin'` — the second layer behind `RegistrableRole`. Not a new policy: the owner-scoped form has been live since #7 |
| 13 | `20260816130000_reconcile_default_partition_policies.sql` | **Phase 1b** (F1). Codifies the four policies that existed live and in **no** migration, so a database rebuilt from these files no longer refuses every audit and request-log write. Proved byte-identical to live before applying, so a no-op against production. Deliberately copies `WITH CHECK (true)` including its weakness — that is **B15** |
| 14 | `20260816140000_login_lookup_returns_role.sql` | **Phase 1b** (FR-A2a). `app.lookup_user_for_login` returns `role`, so `login()` can refuse administrators at the public endpoint. A return-type change needs a DROP, and **the DROP takes the REVOKE, GRANT and COMMENT with it** — all four are re-issued |
| 15 | `20260816150000_two_factor_status_view_security_invoker.sql` | **Phase 2** (B1). `two_factor_status_v` ran as its **owner**, so the policies underneath were skipped — measured: 7 of 7 accounts readable from the application role while the table itself returned 0. Now 0 |
| 16 | `20260816160000_column_level_update_grants.sql` | **Phase 2** (B2, B3, B4). The first column-level grants in the schema. `UPDATE` narrowed to `app_user.full_name` and `student_profile.language_pref`; `role`, `status`, `email_verified_at`, `password_hash` and `class_level` stop being self-writable |
| 17 | `20260816170000_split_read_from_write_on_owner_tables.sql` | **Phase 2** (B5, B6, B7). Seven `FOR ALL` policies split. Subscription activation is no longer self-grantable, revocation becomes a **one-way door** (`WITH CHECK (revoked = true)`), and the five progress tables are read-only |
| 18 | `20260816180000_scope_guardian_functions_to_caller.sql` | **Phase 2** (C2). Both guardian functions check their caller. ⚠️ They have **different** callers — the parent confirms, the **student** invites |
| 19 | `20260816190000_revoke_public_execute_on_helpers.sql` | **Phase 2** (C5). Seven helper functions stop being executable by `PUBLIC` (the register said five). `app_backend` is granted explicitly: `is_admin()` is in 35 policies and `current_user_id()` in 41, and without EXECUTE they **error rather than deny** |
| 20 | `20260816200000_language_pref_on_app_user.sql` | **Phase 3** (FR-A8). `language_pref` moves to `app_user`, so every role — not only students — can receive Urdu email; backfill gated on the column not already existing |
| 21 | `20260816210000_change_password_function.sql` | **Phase 3** (FR-A8). `app.change_password` — takes no user identifier; the subject is `app.current_user_id()` |
| 22 | `20260817120000_session_policy_columns.sql` | **Phase 4**. `sessions_invalidated_at`, `family_started_at`, `revoked_at`, `revoked_reason`; `auth_token` UPDATE narrowed to `revoked` |
| 23 | `20260817130000_session_policy_functions.sql` | **Phase 4** (E2, E3, D2). `app.invalidate_sessions`, `app.insert_refresh_token`, `app.rotate_refresh_token` — rotation is one locked statement |
| 24 | `20260817140000_purge_expired_auth_tokens.sql` | **Phase 4**. `app.purge_expired_auth_tokens` with a 30-day grace; scheduled only if `pg_cron` is installed |
| 25 | `20260817150000_missing_updated_at_triggers.sql` | **Phase 5** (D14). The four missing `updated_at` triggers |
| 26 | `20261004120000_classroom_membership_boundary.sql` | **Classroom Phase 1** (B9, B10, B11). All direct writes to `enrollment` and `join_code`, and INSERT/DELETE on `classroom_space`, revoked; `owns_space` gains the subject-scope check; revocable self-declared `teacher_subject_scope`; join-code format and one-live-code index; set-returning RLS helpers. **Reverses the `join_code_owner` decision** (`database.md`). *Applied 2026-10-04* |
| 27 | `20261004120100_classroom_space_functions.sql` | **Classroom Phase 1**. The eight functions that are now the only classroom writers: create, rotate/disable code, join (board/class/group match, guardian gate, 300-member cap, removed ≠ rejoinable), leave, remove, people, my spaces. *Applied 2026-10-04* |
| 28 | `20261004130000_announcement_ownership_and_scheduling.sql` | **Classroom Phase 3** (B27). Announcement insert/update/delete require `author_id` = caller **and** an active owned classroom; `UPDATE` narrowed to `(body, publish_at)`; `publish_at` schedules a post, hidden from members by the read policy until then (no job); `updated_at` trigger, body check, feed and author indexes. *Applied 2026-10-04* |
| 29 | `20261004140000_assignments_and_grading.sql` | **Classroom Phase 4**. `assignment` (owner content, scheduled by `publish_at`, chapter tag held to the subject by a composite foreign key), `assignment_submission` and `submission_grade` — the grade is its own table because all users share one database role. No write grant on either: five functions (draft, turn in, unsubmit, grade, delete) are the only writers, under one advisory lock per (assignment, student). Teachers see turned-in work of active members only; students see a grade once returned; any grade locks the work. *Applied 2026-10-04* |
| 30 | `20261004150000_classroom_files.sql` | **Classroom Phase 6**. `material_attachment` (a teacher's file on one announcement or assignment) and `submission_file` (a student's file on their submission) — metadata only; the bytes live in the private `classroom-files` bucket, which this file also creates (skipped on a plain PostgreSQL shadow; a **WARNING**, not an error, if the role lacks the privilege — then create it by hand: private, 9 MB, PDF/PNG/JPEG/DOCX/PPTX). CHECK constraints hold every object key to its owner's prefix. Five policies: a member sees an attachment once its post is live; a teacher sees a student's file once turned in and while the student is a member. Three writing functions with quotas (5 files and 20 MiB per submission, 10 per post, 2 GiB per classroom) under one advisory lock per classroom; `app.delete_assignment` now returns every stored key. *Applied 2026-10-05; the migration created the bucket* |
| 31 | `20261005120000_submission_links.sql` | **Classroom Phase 6b**. `submission_link`: up to five https links on a student's work, each its own row, readable exactly like a submission file (the student always; the teacher once turned in and while the student is a member). Written only by `app.add_submission_link` (the file's gate and lock; a repeated link is the same row) and `app.remove_submission_link`. The old single `assignment_submission.link_url` is copied in and cleared; the column stays, unread. *Applied 2026-10-05; the live database held no old link to move* |
| 32 | `20261005130000_classroom_chat.sql` | **Classroom Phase 7**. The class chat: `space_message` (class-public, never the tutor `message` table) and `classroom_space.chat_locked`. A member posts with a column-limited `INSERT (space_id, author_id, body)` held by `space_message_insert` to the caller and to `app.can_post_message` — an active, unmuted member of an unlocked, active classroom who passes the guardian gate, or its teacher (who may post while locked). Members read what is not deleted; the teacher (and an administrator) also reads what was. `app.delete_space_message` (soft, retained), `app.set_student_muted` (writes `enrollment.muted_at`) and `app.space_message_tombstones` (deleted ids for the poll). `author_id` is `ON DELETE RESTRICT`: deleting an account keeps its messages. *Applied 2026-10-05; re-verified on the live database* |

Migrations run in **filename order**. That ordering is a dependency declaration, not decoration:
migration 5 forces Row-Level Security on tables migration 4 creates.

**Never edit an applied migration** — add a new one instead. The files and the applied database
*can* diverge, and have: `20260803090000` records a live code path that failed silently because the
applied `guardian_link_update` policy did not match the file. **Read `pg_policies`, not the file,
for what is live.**

The full migration rules — re-runnability, why a changed `RETURNS TABLE` needs drop-then-create, and
why **a drop takes its grant and its comment with it** — are in
[`../backend/Architecture/database.md#migration-rules`](../backend/Architecture/database.md#migration-rules).

## Scope

**Included:** identity and role-based access control · guardian gate · two-factor authentication ·
curriculum taxonomy · classroom and spaces · assessment · learner analytics · tutor sessions ·
subscriptions · security and platform logs

**Deferred to the chatbot layer:** knowledge-base content (`kb_document`, `curriculum_item`,
`textbook_figure`, `urdu_note_item`, `glossary_term`) and the vector store.

## Design decisions

- **Auth is application-managed.** FastAPI issues its own JSON Web Tokens and hashes passwords with
  argon2id. Supabase Auth (`auth.users`) is deliberately not used, so `app_user` holds
  `password_hash` itself and `auth.uid()` does not exist here.
- **Row-Level Security is defence in depth.** The frontend never talks to Supabase directly —
  FastAPI is the only client — but Row-Level Security is enabled and *forced* so a leaked key or an
  application bug still cannot expose one student's data to another. **Read the
  [Known gaps](../backend/Architecture/database.md#known-gaps) before relying on that sentence:**
  19 findings record where this second layer does not currently hold.
- **Answer keys are isolated.** `question_key` is a separate table with **no Row-Level Security
  policy at all**, so `app_backend` can never read it. Grading runs under a service role. This is
  the database-level backstop for NFR-8, and it **must never gain a policy**.
- **Chat is owner-only.** No teacher, parent, or admin read path exists for `chat_session` /
  `message` / `visual_aid` — a minor's chat is private (PRD §21 TEL-3).
- **Student Learning Outcomes are soft-retired**, never deleted, so historical mastery keeps its
  meaning across curriculum years.
- **Pre-authentication reads go through narrow `SECURITY DEFINER` functions**, never through the
  Row-Level-Security-bypassing service connection. The exception is then explicit, auditable and
  scoped to the columns one flow needs.

## Setup

Install the Supabase command-line interface once:

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

Note that the Supabase CLI **does not wrap a migration file in a transaction**, which is why every
migration from #5 onward is written to be re-runnable.

## Required manual step — backend role password

The migration creates the `app_backend` role with `NOLOGIN` and no password, because **passwords
must never be committed**. Set it once in the Supabase SQL Editor:

```sql
ALTER ROLE app_backend WITH LOGIN PASSWORD 'your-strong-password';
```

Then point `DATABASE_URL` in `backend/.env` at that role — *not* at `postgres`. Connecting as
`postgres` bypasses Row-Level Security and defeats the whole policy layer. The application refuses
to start if it detects this (`backend/app/core/db.py:119-164`), because it is a failure with no
other symptom: everything works, every test passes, and the entire authorization layer is inert.

## How FastAPI connects

Policies read the acting user from a session variable that every request transaction must set.
**The codebase is entirely synchronous SQLAlchemy** — `Session`, `session.execute`, `sessionmaker`.
There is no `AsyncEngine`, no `async with engine.begin()` and no `await` on a database call
anywhere, so do not copy an async pattern into it.

```python
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_current_user_id(session: Session, user_id: UUID | str) -> None:
    parsed = UUID(str(user_id))
    session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(parsed)},
    )
```

Verbatim at `backend/app/core/db.py:33-59`. Two things there are load-bearing:

- `set_config(..., is_local => true)` is the parameterised equivalent of `SET LOCAL`, which cannot
  take a bind parameter and would otherwise have to be built by string concatenation. Use this form.
- It is **transaction-scoped**. A `commit()` in the middle of a request ends the transaction and
  silently discards the setting; every query after it runs with no user bound and returns **zero
  rows, with no error raised anywhere**. If you are chasing a "the query returns nothing but the row
  is definitely there" bug, look for a stray commit first.

If the variable is never set, `app.current_user_id()` returns `NULL` and owner-scoped policies deny
— fail-closed by design. Endpoints that run *before* a session exists (login, refresh, email
verification, password reset, two-factor, the guardian flow) therefore cannot use a plain query;
they call one of the narrow `SECURITY DEFINER` functions instead. All 71 `app.*` functions
(measured 2026-10-05 on a shadow database built from all 32 files, and on the live database) are catalogued, with their call
sites, in
[`../backend/Architecture/database.md`](../backend/Architecture/database.md#the-app-privileged-functions).

Background jobs that legitimately need unrestricted access (the analytics extract-transform-load
job, the quiz auto-submit sweeper, the trial sweeper, vector reconciliation) use
`get_service_db()` instead. **Nothing in a request path may depend on it.**

## Creating a new migration

```bash
supabase migration new add_something_useful
```

Write plain SQL in the generated file. A new table in `public` needs **four** things, not one,
because grants are forward-looking (`ALTER DEFAULT PRIVILEGES`) while Row-Level Security enablement
was a one-shot loop:

1. `ALTER TABLE … ENABLE ROW LEVEL SECURITY;`
2. `ALTER TABLE … FORCE ROW LEVEL SECURITY;`
3. at least one policy — or a deliberate comment saying why it has none, as `question_key` does;
4. and, if the table is partitioned, steps 1 and 2 repeated on **every partition, including the
   default**.

Then update
[`../backend/Architecture/database.md`](../backend/Architecture/database.md) and
[`database.html`](../backend/Architecture/database.html) **in the same change** and append a line to
[`../Claude/HISTORY.md`](../Claude/HISTORY.md). That is the update mandate in
[`../CLAUDE.md`](../CLAUDE.md), and `supabase/migrations/*` maps to those pages in
[`../Claude/DOC-SYNC-MAP.md`](../Claude/DOC-SYNC-MAP.md).

**The agent never pushes a migration.** It produces the file, verifies it with a dry run against a
shadow or branch database and reports the actual output; the repository owner applies it.

## Notes

- `gen_random_uuid()` (UUIDv4) is used for primary keys. On PostgreSQL 18+ you may switch to
  `uuidv7()` for time-ordered keys and better index locality.
- `audit_log` and `api_request_log` are range-partitioned by `created_at` with a `DEFAULT` partition
  so inserts never fail. **Add monthly/daily partitions and a retention job before production
  traffic — and give every new partition its own `ENABLE` + `FORCE`**, or it is directly readable
  past its parent's admin-only policy. That was a real hole, fixed in `20260802150000`.
- Money is stored in **minor units** (`price_minor integer`, so Rs. 999.00 is `99900`), never as a
  float. The 14-day trial length lives in the `trial_ends_at` column default and the application
  must not carry its own copy of the number.
