# Database

> The EduBridge AI schema as it is actually applied — tables, the complete Row-Level Security
> (RLS) policy catalogue, the `app.*` privileged functions, the invariants, and the known gaps.
>
> **Snapshot: 2026-08-15 · commit `eea0e74` · 11 applied migrations.** Counts and the classroom
> sections re-measured **2026-10-05 on branch `add-classroom`** (33 migration files, all applied with `supabase db push` and re-verified on the live database —
> the four earlier `20261004…` files on 2026-10-04; `20261004150000` (classroom files),
> `20261005120000` (submission links), `20261005130000` (class chat) and `20261005140000`
> (parent overview) on 2026-10-05).
> Source of truth: `supabase/migrations/*.sql`. The applied database, not this file, is
> authoritative for what is live — read `pg_policies` when they disagree, and see
> [Migration rules](#migration-rules) for why they can.

Companion pages: [Index](README.md) · [Architecture](architecture.md) ·
[API endpoints](api-endpoints.md) · [Diagrams (HTML)](database.html)

---

## At a glance — every count with the command that produced it

Run from the repository root.

| Measure | Value | Command |
|---|---|---|
| Migration files | **33** (all applied; `20261005140000` on 2026-10-05) | `ls supabase/migrations/*.sql \| wc -l` |
| `CREATE TABLE` statements | **55** | `grep -hE '^CREATE TABLE' supabase/migrations/*.sql \| wc -l` |
| …of which DEFAULT partitions | **2** | `grep -hE '^CREATE TABLE.*PARTITION OF' supabase/migrations/*.sql \| wc -l` |
| Base tables (55 − 2) | **53** | derived from the two rows above |
| Views | **1** | `grep -hE '^CREATE VIEW' supabase/migrations/*.sql \| wc -l` |
| Enumerated types | **22** | `grep -hE '^CREATE TYPE' supabase/migrations/*.sql \| wc -l` |
| Indexes | **63** (62 plain + 1 unique) | `grep -hE '^CREATE (UNIQUE )?INDEX' supabase/migrations/*.sql \| wc -l` |
| Triggers | **17** | `grep -hE '^CREATE TRIGGER' supabase/migrations/*.sql \| wc -l` |
| `CREATE POLICY` occurrences | **114** | `grep -o 'CREATE POLICY' supabase/migrations/*.sql \| wc -l` |
| …real `CREATE POLICY` statements | **111** | `grep -hE '^[[:space:]]*CREATE POLICY' supabase/migrations/*.sql \| wc -l` |
| **Policy objects the migrations produce** | **98** | `SELECT count(*) FROM pg_policies WHERE schemaname = 'public'` on a shadow database built from all 33 files, and the same 98 on the live database (`20261005140000` creates none; 95 before `20261005130000`, which creates 3; 93 before `20261005120000`, which creates 2; 88 before `20261004150000`, which creates 5; 80 before `20261004140000`, which creates 8; 77 before `20261004130000`, which drops 2 and creates 5; 79 before `20261004120000`, which drops 4 and creates 2) |
| `CREATE OR REPLACE FUNCTION` statements | **85** | `grep -hE '^CREATE OR REPLACE FUNCTION' supabase/migrations/*.sql \| wc -l` |
| Distinct `app.*` function names ever defined | **73** | `grep -ohE 'CREATE OR REPLACE FUNCTION app\.[a-zA-Z0-9_]+' supabase/migrations/*.sql \| sed 's/.*app\.//' \| sort -u \| wc -l` |
| **Live `app.*` functions** (73 − 1 retired) | **72** | `SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app'` on the shadow, and 72 on the live database (2026-10-05; 71 before `20261005140000`, which adds 1; 67 before `20261005130000`, which added 4); `issue_token_for_email` is the one dropped for good |
| `SECURITY DEFINER` lines | **85** | `grep -hE '^[^-]*SECURITY DEFINER' supabase/migrations/*.sql \| wc -l` |
| `SET search_path` lines | **85** | `grep -hE '^SET search_path' supabase/migrations/*.sql \| wc -l` |
| `REVOKE ALL ON FUNCTION … FROM PUBLIC` | **74** | `grep -hE '^REVOKE ALL ON FUNCTION' supabase/migrations/*.sql \| wc -l` |
| `GRANT EXECUTE … TO app_backend` | **72** — lines, not functions; no longer equal to the revokes, because the classroom's internal helpers (`submittable_space`, `lock_submission`, `space_storage_bytes`, `lock_space_files`) are revoked and deliberately never granted (plan R9) | `grep -hE '^GRANT EXECUTE' supabase/migrations/*.sql \| wc -l` |
| `app.*` functions executable by `PUBLIC` | **0** | `aclexplode(proacl)` with `grantee = 0`, on the shadow |
| Implemented HTTP endpoints | **64** (21 auth + 43 classroom) | `grep -cE '^@router\.' backend/app/auth/routes.py backend/app/classroom/routes.py` (plus `/health` in `backend/app/main.py`) |

**Measured from the catalogue (shadow database built from all 33 files, 2026-10-05): 71 of the 72 live `app.*` functions
carry `search_path`.** The exception is `app.set_updated_at()`
(`20260801120000_initial_schema.sql:85`), a plain trigger function that is not `SECURITY DEFINER`
and therefore has nothing to escalate. Two functions are not `SECURITY DEFINER`: that trigger, and
`app.current_user_id()` (`20260801120100_rls_policies.sql:49`), which only reads a session setting.
The grep counts above count *lines*, which drift from function counts when a later migration
re-states a definition; the catalogue query is the authority.

### Why 73, 73 and 72 are all correct

> **Historical — the 2026-08-16 reconciliation, kept for its method.** The current numbers are in the
> table above and were measured from a shadow database rather than derived by arithmetic; the lesson
> below (statements ≠ objects ≠ live) still applies.

Three different numbers describe the same policy layer, and conflating them is the easiest
mistake to make here:

* **73** — occurrences of the string `CREATE POLICY` in the migration files.
* **72** — actual `CREATE POLICY` statements. The 73rd occurrence is prose:
  `20260802140000_reference_read_and_auth_lookups.sql:27` explains that
  "Postgres has no CREATE POLICY IF NOT EXISTS".
* **73** — **live policy objects in the applied database**, which is the number that matters and
  the number this page catalogues in full.

The arithmetic from statements to objects:

```
73  CREATE POLICY statements
 −2  statements that live inside the FOREACH loop at 20260801120100:232-247
 +12  policy objects that loop creates (2 policies × 6 curriculum tables)
−10  drop-and-recreate restatements of names that already exist
     (6 curriculum *_read in 20260802140000; app_user_insert in 20260802150000
      and again in 20260816120000; guardian_link_create and guardian_link_update
      in 20260803090000)
 = 73 policy objects THE MIGRATIONS PRODUCE
 +4  policies that exist in the live database and in NO migration — see below
 = 77 policy objects currently live
```

> ⚠️ **Finding F1 — the migrations and the live database disagree.** Measured 2026-08-16 by
> querying `pg_policy` directly; the earlier figure of 73 in this document was derived by counting
> statements in the migration files and was wrong about what is deployed.
>
> Four policies exist **only** in the live database:
>
> | Table | Policy | Verb | Predicate |
> |---|---|---|---|
> | `audit_log_default` | `audit_default_admin_read` | SELECT | `app.is_admin()` |
> | `audit_log_default` | `audit_default_insert` | INSERT | `WITH CHECK (true)` |
> | `api_request_log_default` | `reqlog_default_admin_read` | SELECT | `app.is_admin()` |
> | `api_request_log_default` | `reqlog_default_insert` | INSERT | `WITH CHECK (true)` |
>
> They mirror the parent tables' `audit_admin_read` / `audit_insert`, so they look deliberate —
> somebody applied them in the SQL editor and never wrote the migration. `grep` across
> `supabase/migrations/` finds none of the four names.
>
> **Why this is more than untidiness.** `20260802150000:33-38` enables *and forces* Row-Level
> Security on both default partitions. A database rebuilt from the migration files alone would
> therefore have those partitions forced with **no policies at all** — and PostgreSQL applies a
> partition's own policies to rows routed into it from the parent. So a fresh environment may refuse
> every audit and request-log write, while production is fine. That is the worst shape a divergence
> can take: it cannot be reproduced anywhere the migrations are the source of truth.
>
> **FIXED, phase 1b (2026-08-16)** — `20260816130000_reconcile_default_partition_policies.sql`.
> Written from `pg_policy` rather than from what someone assumes was intended, and dry-run first:
> the four policies it creates were proved byte-identical to the live ones (command, `USING`,
> `WITH CHECK` and roles) before it was applied, so against production it is a no-op. Its value is
> that a database rebuilt from the migrations alone now gets them.
>
> It deliberately copies `WITH CHECK (true)` **including its weakness** — that is finding B15 on the
> parent tables. Phase 2 tightens parent and partition together; reconciling and redesigning in one
> file would make it impossible to tell which change caused what.
>
> This was also the concrete answer to whether the migrations replay from zero into the deployed
> schema: **they did not, by exactly four policies.** Tables, views, `app.*` functions, triggers and
> enum types showed zero divergence when live object names were diffed against the migration corpus.
>
> `tests/integration/test_rls.py::TestPartitionDirectAccessDenied` still passes, and its docstring
> is still inaccurate — it says the partitions were left "with no policies", which was true of the
> migration corpus before `20260816130000` and was never true of the database.

Scaffolded-only directories, named honestly: `ml/`, `mcp-servers/`, `infra/` and
`backend/app/workers/` contain **`.gitkeep` files only** (`mcp-servers/` and `infra/` additionally
carry a `.env.example`). They are scaffolded, not empty, and no code lives in them yet —
`find ml mcp-servers infra backend/app/workers -type f`.

---

## The connection and role model

Authentication is application-managed. FastAPI issues its own JSON Web Tokens (JWTs) and hashes
passwords with argon2id; Supabase Auth (`auth.users`) is deliberately unused, so `auth.uid()` does
not exist here. Every policy instead reads a transaction-scoped session setting.

| Piece | Where | What it does |
|---|---|---|
| `app_backend` role | `20260801120100_rls_policies.sql:27-33` | `NOLOGIN NOBYPASSRLS`; the role the application connects as. Its password is set out of band and never committed. |
| Table-wide grants | `20260801120100_rls_policies.sql:36-41` | `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public`, plus `ALTER DEFAULT PRIVILEGES` so every future table is granted automatically. |
| `ENABLE` + `FORCE` loop | `20260801120100_rls_policies.sql:126-137` | Enables *and forces* RLS on every `pg_tables` row in `public` whose name does not end `_default`. `FORCE` is what stops the table owner bypassing the policies. |
| The binding | `backend/app/core/db.py:33-59` | `SELECT set_config('app.current_user_id', :uid, true)` — the parameterised equivalent of `SET LOCAL`. |
| The reader | `app.current_user_id()`, `20260801120100_rls_policies.sql:49-54` | `NULLIF(current_setting('app.current_user_id', true), '')::uuid` |
| Boot-time guard | `backend/app/core/db.py:119-164` | Refuses to start if the connected role reports `rolsuper` or `rolbypassrls`, because either makes the whole policy layer inert with no other symptom. |

**The binding is transaction-scoped, and that is load-bearing.** A stray `commit()` mid-request
ends the transaction and silently discards the setting; every query after it runs with no user
bound and returns **zero rows, with no error anywhere**. `backend/app/core/db.py:45-50` documents
this as the first thing to check when a row that definitely exists cannot be read.

Unset therefore means deny, not allow — the fail-closed default. That property is why
`20260802140000_reference_read_and_auth_lookups.sql:102-106` explicitly *rejects* the tempting
policy form `USING (app.current_user_id() IS NULL)` for pre-authentication paths: it would turn
the fail-closed default into fail-open on exactly the code path most likely to carry the bug.

Two connections exist. `engine` (`backend/app/core/db.py:12`) connects as `app_backend`.
`service_engine` (`backend/app/core/db.py:26`) connects as a role that bypasses RLS and is for
background jobs only — the extract-transform-load job, the trial sweeper, reconciliation. Nothing
in a request path may depend on it; pre-authentication reads go through the narrow
`SECURITY DEFINER` functions catalogued below instead.

---

## Tables by domain

Every heading cites the migration file and the line the `CREATE TABLE` begins on. Clustered
entity-relationship diagrams — one per domain, never one unreadable master — are in
[`database.html`](database.html).

### Identity and role-based access control

| Table | Defined at | Notes |
|---|---|---|
| `app_user` | `20260801120000_initial_schema.sql:97` | `email citext UNIQUE`, `password_hash` (argon2id), `role user_role`, `status user_status`, `email_verified_at`, **`language_pref language_code NOT NULL DEFAULT 'en'`** (added by `20260816200000`), **`sessions_invalidated_at`** (added by `20260817120000` — see below), soft-delete `deleted_at`. Trigger `trg_app_user_updated` at `:109`. |
| `student_profile` | `:114` | `board`, `class_level` (9–12), `student_group`, `medium`, `language_pref` (⚠️ **superseded — read by nothing**, see below). `ck_group_matches_class` at `:124` forbids an FSc group on a Matric class and vice versa. |
| `teacher_profile` | `:133` | `institution` only. |
| `parent_profile` | `:140` | Timestamps only. |
| `admin_profile` | `:146` | Free-text `scope`. |

`class_level` on `student_profile` is the input to the parental-consent gate — see
[B4](#b-known-gaps--the-database-would-not-catch-a-missed-check).

> ⚠️ **`language_pref` EXISTS ON BOTH TABLES, AND ONLY `app_user` IS READ (`20260816200000`).**
>
> It began on `student_profile`. FR-A8 grants account management to **all four roles** and requires
> the stored preference to govern outgoing email — but the lookup behind every outgoing mail,
> `app.lookup_user_for_email_flow`, LEFT JOINed a table that teachers, parents and administrators
> have no row in. It returned `NULL` for them and the caller fell back to English, silently and for
> ever. **No non-student could receive Urdu mail**, and no endpoint work could fix it, because there
> was nowhere to store the answer. Measured on the live administrator account before the migration:
> `language_pref -> None`; after: `'en'`.
>
> `app_user.language_pref` is now the single source of truth for outgoing email **and** for
> `MeResponse.profile.language_pref` (`_ME_QUERY` selects `u.language_pref`, not `sp.`), so the
> settings screen cannot display one language while mail is sent in another.
>
> The `student_profile` column is **deliberately kept and deliberately unread**. Dropping it would
> take `20260816160000`'s `GRANT UPDATE (language_pref) ON student_profile` with it, leaving that
> table with no updatable column at all and deleting a passing authorization test for no gain.
> Registration writes both with the same value; only `app_user` is ever updated afterwards. **If you
> are reading `sp.language_pref` anywhere, that is the bug.**

### Guardian link — the parental-consent gate

| Table | Defined at | Notes |
|---|---|---|
| `guardian_link` | `20260801120000_initial_schema.sql:156` | `parent_id`, `student_id`, `status guardian_status`, `verification_method`, `verified_at`. |

Three constraints carry the gate's meaning: `ck_guardian_not_self` (`:165`) stops a student
registering as their own parent, `ck_guardian_verified_has_ts` (`:166`) forbids a verified link
with no timestamp, and `uq_guardian_pair` (`:168`) makes the pair unique.

After `20260803090000_guardian_link_write_boundary.sql` a link can reach `'verified'` through
**exactly one path**: `app.confirm_guardian_link`, which requires an unexpired, unrevoked, one-time
`guardian_invite` token. Every other write can only produce `'pending'` or `'revoked'` — the
INSERT policy pins `status = 'pending'` (`:54-60`) and the UPDATE policy's `WITH CHECK` forbids
`'verified'` (`:69-72`).

### Two-factor authentication (SEC-14)

| Table | Defined at | Notes |
|---|---|---|
| `two_factor_enrollment` | `20260801120000_initial_schema.sql:193` | One row per user. `method`, `status`, `totp_secret_encrypted bytea` (AES-256 ciphertext; the key lives in application config, so a database dump alone yields nothing usable), `last_used_counter` (Time-based One-Time Password replay guard), `failed_attempts`, `locked_until`. |
| `two_factor_backup_code` | `:223` | Ten per enrolment, argon2id-hashed, single use via `used_at`. Plaintext exists only in the one response that issues them. |
| `two_factor_status_v` **(view)** | `:236` | **The caller's own** two-factor method, status, lockout state and unused-code count, with **no secret and no code hash**. ⚠️ **Not an administrator view** — it was described as one until `20260816150000` gave it `security_invoker = true` (finding **B1**), and with both underlying policies owner-scoped an administrator now sees only their own row. Cross-account 2FA state belongs to `GET /api/auth/2fa/status`. |

Three CHECK constraints keep the state machine honest: `ck_totp_requires_secret`,
`ck_email_otp_has_no_secret` and `ck_active_is_confirmed` (`:209-214`) — an `active` enrolment
cannot exist without a `confirmed_at`.

The base tables carry **no admin policy on purpose** (`20260801120100_rls_policies.sql:214-218`):
RLS is row-level, not column-level, so an admin row policy would have handed administrators the
encrypted secret column too. The view exists so they do not need it. That the view itself is not
protected is [B1](#b-known-gaps--the-database-would-not-catch-a-missed-check).

### Curriculum taxonomy

| Table | Defined at | Notes |
|---|---|---|
| `board` | `20260801120000_initial_schema.sql:250` | `code board_code` — PCTB, STBB. |
| `class_level` | `:257` | 9–12 per board, `uq_class_level`. |
| `subject` | `:268` | Defined **once per (board, class)**, never per elective group, so curriculum content is not duplicated. `content_strategy` drives agent routing. |
| `subject_group` | `:281` | Which elective groups take each subject. |
| `chapter` | `:288` | `uq_chapter (subject_id, number)`. |
| `slo` | `:298` | Student Learning Outcomes. `retired_at` **soft-retires** on a syllabus change; rows are never deleted, so historical mastery keeps its meaning. |
| `teacher_subject_scope` | `:311` | Many-to-many least-privilege scope: which subjects a teacher may see. **Self-declared** since `20261004120000`: `app.create_space` writes the row when a teacher creates a classroom (owner decision 2026-10-03). An administrator withdraws it by stamping `revoked_at` — `DELETE` is revoked from `app_backend`, because a deleted row would be silently re-declared by the teacher's next classroom. |

Seeded by `20260801120200_seed_reference_data.sql` — two boards, four class levels each, the
subject matrix documented at `:6-19`, and the group mappings at `:91-96`. Idempotent.

### Classroom and spaces

| Table | Defined at | Notes |
|---|---|---|
| `classroom_space` | `20260801120000_initial_schema.sql:324` | `ck_teacher_space_has_subject` (`:334`) forces a teacher space to declare its subject, because subject-scoping depends on it. Since `20261004120000`: `ck_space_owner_is_teacher` (the enum still lists `parent`, but parents no longer create spaces — `prd.md` §4.2 v0.3.5) and `ck_space_title` (1–120 characters). **Created only by `app.create_space`; never deleted** — `status = 'archived'` is the end state, and the owner may write only `title` and `status` — and, since `20261005130000`, `chat_locked` (default `false`; while true only the teacher posts in the class chat). |
| `join_code` | `:341` | Unique code, revocable, optional expiry. Never readable by students — they receive it out of band. Since `20261004120000`: `ck_join_code_format` (`^[A-HJ-NP-Z2-9]{8}$`, 2⁴⁰ codes, minted in Python by `app/classroom/codes.py`) and `uq_join_code_one_live` (one unrevoked code per space). **Written only by `app.rotate_join_code` / `app.disable_join_code`.** |
| `enrollment` | `:351` | Joining a space **is** the consent record. `left_at` is the soft leave. Since `20261004120000`: `removed_at` (set by the teacher; a removed student cannot rejoin with the code, one who left can — `ck_enrollment_removed_has_left`) and `muted_at` (written by `app.set_student_muted` since `20261005130000`; survives leave and rejoin). **Written only by `app.join_space_by_code`, `app.leave_space`, `app.remove_student` and `app.set_student_muted`.** |
| `announcement` | `:364` | Space-scoped, author-attributed. Since `20261004130000`: `updated_at` (with `trg_announcement_updated`), `publish_at` (default `now()`; a future value **schedules** the post and the member read policy hides it until then — no job publishes it), `ck_announcement_body` (1–5000 characters after trimming), `ix_announcement_feed (space_id, publish_at DESC, id DESC)` for the keyset-paginated stream (replaces `ix_announcement_space`) and `ix_announcement_author` for the `ON DELETE RESTRICT` check. The owner may `UPDATE` only `body` and `publish_at`; INSERT and DELETE stay table-level and are held by the policies. Since `20261004150000`: `uq_announcement_id_space (id, space_id)`, the target of an attachment's composite key. |
| `assignment` | `20261004140000:59` | Owner content, like `announcement`: author-attributed, scheduled by `publish_at` (members cannot read a future one). `subject_id` is denormalised for per-subject reports and held to the classroom's by the composite key `fk_assignment_space_subject (space_id, subject_id)`; the optional `chapter_id` is held to the same subject by `fk_assignment_chapter_subject (chapter_id, subject_id)` — a chapter from another subject is a foreign-key violation, not a service check. `ck_assignment_title` (1–200), `ck_assignment_instructions` (≤ 10 000), `ck_assignment_points` (1–1000 or NULL), `ck_assignment_due_after_publish`. The owner may `UPDATE` only `title, instructions, due_at, points, chapter_id, publish_at`; INSERT is table-level and held by `assignment_insert`; **no DELETE grant** — `app.delete_assignment` only. |
| `assignment_submission` | `20261004140000:93` | One per (assignment, student) — `uq_submission_one_per_student`. `turned_in_at` (NULL = draft, stamped with `clock_timestamp()`) is the only state: **late, missing and graded are derived** (`app/classroom/status.py`), never stored. `link_url` (with `ck_submission_link`) is **superseded since `20261005120000`** — copied into `submission_link`, cleared, and kept unread, because `app.save_submission_draft` still takes `p_link` (the service passes `NULL`). `uq_submission_id_space_student` is the target for submission files and links. **No write grant**: written only by `app.save_submission_draft`, `app.turn_in_submission` and `app.unsubmit_submission`. |
| `submission_grade` | `20261004140000:117` | The teacher's grade (`numeric(6,2)`) and private feedback, keyed `(assignment_id, student_id)`. **A separate table, not a column on the submission**: every user shares one database role, so a teacher-owned column on a student-owned row would be writable by both. `returned_at` is when the student may see it — set once, never cleared. **No write grant**: written only by `app.save_grade`. |
| `material_attachment` | `20261004150000:43` | A teacher's file on an announcement **or** an assignment — exactly one (`ck_material_one_parent`), each by a composite key `(announcement_id, space_id)` / `(assignment_id, space_id)` so the row's `space_id` is always its parent's. **`ck_material_key`**: the object key must be `s/<space_id>/<32 hex>` — a key naming another classroom is a CHECK violation. `ck_material_type` (PDF, PNG, JPEG, DOCX, PPTX), `ck_material_size` (1 byte to 9 MiB), `ck_material_filename` (1–255), `ck_material_sha` (SHA-256 hex). Cascades with its parent. Grants: `SELECT`, and `DELETE` for the owner under `material_owner_delete`; **written only by `app.add_material_attachment`**; no `UPDATE` — a row is immutable. |
| `submission_file` | `20261004150000:76` | A student's file on their submission. `fk_subfile_submission (submission_id, space_id, student_id)` targets `uq_submission_id_space_student`, so a file can only ever belong to its own student's submission in its own classroom. **`ck_subfile_key`**: `u/<space_id>/<student_id>/<32 hex>`. Same type, size, filename and hash checks. **`SELECT` only**: written only by `app.add_submission_file` and `app.remove_submission_file`. |
| `submission_link` | `20261005120000:25` | A link on a student's work (classroom Phase 6b) — up to five, each its own row. `fk_sublink_submission (submission_id, space_id, student_id)` targets `uq_submission_id_space_student`, like a file. `ck_sublink_url`: `https://` and no whitespace, at most 2048 characters; `uq_sublink_url (submission_id, url)` — the same link twice is one row. **`SELECT` only**: written only by `app.add_submission_link` and `app.remove_submission_link`. |
| `space_message` | `20261005130000:45` | The class chat (classroom Phase 7, `prd.md` CL-5) — **class-public**, and deliberately **not** the tutor `message` table ([invariant 8](#8-chat-is-owner-only)). `ck_space_message_body` (1–1000 characters after trimming); `ck_space_message_deleted_pair` (`deleted_at` and `deleted_by` set together). `created_at` defaults to `clock_timestamp()`: the poll's cursor needs the real insert time, and `now()` is frozen per transaction. `author_id` and `deleted_by` are `ON DELETE RESTRICT` — **deleting an account does not delete what it said in a class** (owner decision 2026-10-05); `space_id` cascades. Indexes: `ix_space_message_feed (space_id, created_at, id)`, the partial `ix_space_message_deleted (space_id, deleted_at)` for tombstones, `ix_space_message_author`, the partial `ix_space_message_deleted_by`. Grants: `SELECT`, and **`INSERT (space_id, author_id, body)` only**, so neither a message's time nor its deletion can be supplied; no UPDATE or DELETE — soft-deleted only by `app.delete_space_message`. |

### Assessment

| Table | Defined at | Notes |
|---|---|---|
| `past_paper` | `20260801120000_initial_schema.sql:379` | Unique on (board, class, subject, year). |
| `question` | `:389` | `stem`, `choices jsonb` (NULL for free response), `marks`. GIN index on `choices` at `:401`. |
| **`question_key`** | `:404` | **Answer keys. Separate table, no policy, ever.** See [the invariants](#invariants-and-the-reason-for-each). |
| `question_slo` | `:413` | Fractional attribution `weight numeric(4,3)` so a wrong answer is neither double-counted nor dropped across the many-to-many mapping. |
| `item_difficulty` | `:422` | Item Response Theory parameters `irt_a`, `irt_b`, `irt_c`. |
| `slo_frequency_cluster` | `:430` | How often an outcome appears in past papers, per board. |
| `quiz` | `:441` | `ck_quiz_window` (`:455`) forces `time_close > time_open`. |
| `quiz_question` | `:462` | Ordering table. |
| `quiz_attempt` | `:469` | `uq_attempt_one_per_student` (`:479`); `version integer` is an optimistic lock; the partial index at `:482` is what the auto-submit sweeper scans. |
| `attempt_answer` | `:486` | `correct` is graded server-side only. |

### Learner analytics

| Table | Defined at | Notes |
|---|---|---|
| `mastery_estimate` | `20260801120000_initial_schema.sql:501` | Bayesian Knowledge Tracing state per (student, outcome): `p_mastery`, `p_transit`, `p_guess`, `p_slip`, all range-checked. |
| `coverage_record` | `:515` | Syllabus coverage percentage per (student, subject, date). |
| `exam_readiness_score` | `:524` | Score plus `expected_marks`. |
| `review_schedule` | `:534` | Spaced repetition: `due_at`, `interval_days`. |

Read paths differ by role on purpose: a **verified** guardian reads every subject; a teacher reads
only through `app.teaches_student_subject`, which requires both an active enrolment in a space they
own and a matching `teacher_subject_scope` row.

### Tutor sessions

| Table | Defined at | Notes |
|---|---|---|
| `chat_session` | `20260801120000_initial_schema.sql:549` | Owner is `student_id`. |
| `message` | `:557` | `role message_role`, `slo_refs uuid[]` for grounding citations. |
| `visual_aid` | `:568` | `payload jsonb` is a typed spec only, rendered sandboxed. |

**Owner-only, with no teacher, parent or admin read path anywhere** — a minor's chat is private
(product requirements §4.2, §21 TEL-3). This invariant was re-verified in the Epic 1 review and
**holds**: no privileged function touches these three tables.

### Security and operations

| Table | Defined at | Notes |
|---|---|---|
| `agent_component` | `20260801120000_initial_schema.sql:583` | Skills and Model Context Protocol servers unified into one table so `permission_manifest` can hold a single valid foreign key rather than a polymorphic reference. |
| `permission_manifest` | `:597` | `granted_scopes`, `db_scopes`, `network jsonb` defaulting to `{"default":"deny","allow":[]}`, `resource_limits`. |
| `agent_sbom_entry` | `:607` | Software Bill of Materials: provenance, `content_hash`, `signature`. |
| `vetting_result` | `:617` | `findings`, `claim_vs_actual`, `verdict`. |
| `audit_log` | `:629` | Security audit trail. **Range-partitioned by `created_at`**; the primary key is `(id, created_at)` because a partitioned table's key must include the partition key. |
| `audit_log_default` | `:638` | DEFAULT partition. |
| `api_request_log` | `:642` | One row per API call, for the admin daily-logs panel. Also range-partitioned. |
| `api_request_log_default` | `:657` | DEFAULT partition. |

### Subscription and social identity

| Table | Defined at | Notes |
|---|---|---|
| `subscription_plan` | `20260802120000_subscriptions_and_oauth.sql:40` | Reference data, one row seeded at `:115` — `standard`, 99900 minor units (Rs. 999.00), PKR, monthly. Money is stored in **minor units so it is never a float**. |
| `subscription` | `:63` | One per user (`uq_subscription_user`). `trial_ends_at` defaults to `now() + interval '14 days'` — **that default is the source of truth for trial length; the application must not carry its own copy of the number** (`:68-70`). `ck_subscription_active_has_period` forces an active row to say when its paid period ends. |
| `oauth_identity` | `:96` | Reserved for deferred social sign-in. `provider_user_id` is the provider's opaque `sub` claim, not an email. **Nothing writes to this table yet** (`:93`). |

`onboarding_state` is a **derived API field, not a column** (`20260802120000:14-22`). It is computed
from `app_user.email_verified_at`, `two_factor_enrollment.status`, `guardian_link.status` and
`subscription.status`. The migration states the rule the backend must honour: absence of a
subscription row is **not** the same as `trialing` — derive it fail-closed, so a failed insert can
never silently grant free access forever.

---

## The complete Row-Level Security policy catalogue

**All 98 live policy objects** (shadow and live agree, 2026-10-05; the parent overview, `20261005140000`, adds none). Every one is `TO app_backend`; no other role has a policy. An empty
cell means the clause is absent from the policy, which is not the same as `true` — an absent
`WITH CHECK` on an `UPDATE` policy means PostgreSQL falls back to the `USING` expression, and an
absent `USING` on an `INSERT` policy is simply not applicable.

Read `app.current_user_id()` as **`cuid()`** throughout, purely to keep the table legible.

`file:line` is the **live** definition — where a policy was later dropped and recreated, the
citation points at the recreation, with the superseded original noted.

### Identity — `app_user`, profiles

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `app_user` | `app_user_self_read` | SELECT | `id = cuid() OR app.is_admin()` | — | `20260801120100:143` |
| `app_user` | `app_user_self_update` | UPDATE | `id = cuid()` | `id = cuid()` | `20260801120100:147` |
| `app_user` | `app_user_insert` | INSERT | — | `id = cuid() AND role <> 'admin'` | `20260816120000:39` (narrows `20260802150000:51`, which restated `20260801120100:157`) |
| `student_profile` | `student_profile_read` | SELECT | `user_id = cuid() OR app.is_verified_guardian_of(user_id) OR app.is_admin()` | — | `20260801120100:160` |
| `student_profile` | `student_profile_write` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260801120100:168` |
| `teacher_profile` | `teacher_profile_self` | ALL | `user_id = cuid() OR app.is_admin()` | `user_id = cuid()` | `20260801120100:173` |
| `parent_profile` | `parent_profile_self` | ALL | `user_id = cuid() OR app.is_admin()` | `user_id = cuid()` | `20260801120100:178` |
| `admin_profile` | `admin_profile_self` | ALL | `user_id = cuid() OR app.is_admin()` | `app.is_admin()` | `20260801120100:183` |

### Guardian link

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `guardian_link` | `guardian_link_participants` | SELECT | `parent_id = cuid() OR student_id = cuid() OR app.is_admin()` | — | `20260801120100:190` |
| `guardian_link` | `guardian_link_create` | INSERT | — | `(student_id = cuid() OR parent_id = cuid()) AND parent_id <> student_id AND status = 'pending'` | `20260803090000:54` (supersedes `20260801120100:198`) |
| `guardian_link` | `guardian_link_update` | UPDATE | `parent_id = cuid()` | `parent_id = cuid() AND status <> 'verified'` | `20260803090000:69` (supersedes `20260801120100:205`) |

### Tokens and two-factor authentication

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `auth_token` | `auth_token_owner` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260801120100:209` |
| `two_factor_enrollment` | `two_factor_enrollment_owner` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260801120100:219` |
| `two_factor_backup_code` | `two_factor_backup_code_owner` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260801120100:224` |

### Curriculum taxonomy

The six `*_read` policies below were created by the `FOREACH` loop at `20260801120100:232-247` with
`USING (app.current_user_id() IS NOT NULL)`, then **dropped and recreated with `USING (true)`** by
`20260802140000:48-71`. The six `*_admin_write` policies still come from the loop.

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `board` | `board_read` | SELECT | `true` | — | `20260802140000:55` |
| `board` | `board_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `class_level` | `class_level_read` | SELECT | `true` | — | `20260802140000:58` |
| `class_level` | `class_level_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `subject` | `subject_read` | SELECT | `true` | — | `20260802140000:61` |
| `subject` | `subject_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `subject_group` | `subject_group_read` | SELECT | `true` | — | `20260802140000:64` |
| `subject_group` | `subject_group_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `chapter` | `chapter_read` | SELECT | `true` | — | `20260802140000:67` |
| `chapter` | `chapter_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `slo` | `slo_read` | SELECT | `true` | — | `20260802140000:70` |
| `slo` | `slo_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:241` (loop) |
| `teacher_subject_scope` | `tss_read` | SELECT | `teacher_id = cuid() OR app.is_admin()` | — | `20260801120100:249` |
| `teacher_subject_scope` | `tss_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:253` |

### Classroom

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `classroom_space` | `space_visible` | SELECT | `owner_id = cuid() OR app.is_enrolled_in(id) OR app.is_admin()` | — | `20260801120100:261` |
| `classroom_space` | `space_owner_update` | UPDATE | `app.owns_space(id)` | `app.owns_space(id)` | `20261004120000` §2 — replaces `space_owner_write` (FOR ALL, no role check: **B10**). Column grant `UPDATE (title, status)` only — and `chat_locked` since `20261005130000`; no INSERT/DELETE grant |
| `join_code` | `join_code_owner_read` | SELECT | `space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin())` | — | `20261004120000` §3 — replaces `join_code_owner` (FOR ALL); no write grant at all |
| `enrollment` | `enrollment_visible` | SELECT | `student_id = cuid() OR app.owns_space(space_id) OR app.is_admin()` | — | `20260801120100:281` |
| `announcement` | `announcement_owner_read` | SELECT | `space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin())` | — | `20261004130000:67` |
| `announcement` | `announcement_member_read` | SELECT | `space_id IN (SELECT app.my_member_space_ids()) AND publish_at <= now()` — a scheduled post is invisible to members **at the database** | — | `20261004130000:72` |
| `announcement` | `announcement_insert` | INSERT | — | `author_id = cuid() AND app.owns_active_space(space_id)` | `20261004130000:76` |
| `announcement` | `announcement_update` | UPDATE | `author_id = cuid() AND app.owns_active_space(space_id)` | same expression; column grant `UPDATE (body, publish_at)` only | `20261004130000:80` |
| `announcement` | `announcement_delete` | DELETE | `author_id = cuid() AND app.owns_active_space(space_id)` | — | `20261004130000:85` |
| `assignment` | `assignment_owner_read` | SELECT | `space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin())` | — | `20261004140000:234` |
| `assignment` | `assignment_member_read` | SELECT | `space_id IN (SELECT app.my_member_space_ids()) AND publish_at <= now()` | — | `20261004140000:240` |
| `assignment` | `assignment_insert` | INSERT | — | `author_id = cuid() AND app.owns_active_space(space_id)` | `20261004140000:244` |
| `assignment` | `assignment_update` | UPDATE | `author_id = cuid() AND app.owns_active_space(space_id)` | the same **and** `app.points_compatible(id, points)` — points can never drop below an existing grade | `20261004140000:248` |
| `assignment_submission` | `submission_read_own` | SELECT | `student_id = cuid()` | — | `20261004140000:259` |
| `assignment_submission` | `submission_teacher_read` | SELECT | `turned_in_at IS NOT NULL AND (space_id, student_id) IN (SELECT … FROM app.my_taught_students())` — **turned-in work of active members only**; a draft is the student's own | — | `20261004140000:263` |
| `submission_grade` | `grade_teacher_read` | SELECT | `(space_id, student_id) IN (SELECT … FROM app.my_taught_students())` | — | `20261004140000:271` |
| `submission_grade` | `grade_student_read_returned` | SELECT | `student_id = cuid() AND returned_at IS NOT NULL` | — | `20261004140000:275` |
| `material_attachment` | `material_owner_read` | SELECT | `space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin())` | — | `20261004150000:159` |
| `material_attachment` | `material_member_read` | SELECT | `space_id IN (SELECT app.my_member_space_ids()) AND app.material_parent_published(announcement_id, assignment_id)` — a scheduled post's attachment is hidden **with** the post | — | `20261004150000:163` |
| `material_attachment` | `material_owner_delete` | DELETE | `app.owns_active_space(space_id)` | — | `20261004150000:168` |
| `submission_file` | `subfile_read_own` | SELECT | `student_id = cuid()` | — | `20261004150000:175` |
| `submission_file` | `subfile_teacher_read` | SELECT | `(space_id, student_id) IN (SELECT … FROM app.my_taught_students()) AND EXISTS (turned-in submission)` — both conditions stated here, not inherited from `submission_teacher_read` through a subquery | — | `20261004150000:182` |
| `submission_link` | `link_read_own` | SELECT | `student_id = cuid()` | — | `20261005120000:59` |
| `submission_link` | `link_teacher_read` | SELECT | `(space_id, student_id) IN (SELECT … FROM app.my_taught_students()) AND EXISTS (turned-in submission)` — the file rule, stated in full | — | `20261005120000:63` |
| `space_message` | `space_message_owner_read` | SELECT | `space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin())` — deleted messages included: retained for review | — | `20261005130000:120` |
| `space_message` | `space_message_member_read` | SELECT | `deleted_at IS NULL AND space_id IN (SELECT app.my_member_space_ids())` — a muted member, or one in a locked chat, still reads | — | `20261005130000:126` |
| `space_message` | `space_message_insert` | INSERT | — | `author_id = cuid() AND app.can_post_message(space_id)` — an active, unmuted member of an unlocked, active classroom who passes the guardian gate, or its teacher (who may post while it is locked) | `20261005130000:130` |

`enrollment_student_join` (INSERT into **any** space) and `enrollment_leave` (UPDATE with no
`WITH CHECK`) were **dropped** by `20261004120000` §4 — finding **B9** — and `app_backend` holds no
write grant on `enrollment`. Every enrolment change goes through a function in the
[classroom section](#classroom--post-apispaces-functions).

`announcement_read` and `announcement_write` (`20260801120100:298-304`) were **dropped** by
`20261004130000` — finding **B27**: the write policy never checked `author_id`, so a space owner
could post as anyone, and there was no UPDATE or DELETE policy at all. ⚠️ `now()` in
`announcement_member_read` is the **transaction** start, so a post becomes visible to the first
query that begins after its `publish_at`, never part-way through one.

The assignment tables (`20261004140000`) have no DELETE policy, and `assignment_submission` and
`submission_grade` no write policy at all: with no write grant either, every change goes through
a function in the [assignments section](#classroom--assignment-functions). **Leaving ends teacher
visibility** (user story 7.1) is `app.my_taught_students()`: it lists active members only, so the
moment a student leaves, their submissions and grades drop out of both teacher read policies.

The file tables (`20261004150000`) follow the thing a file is attached to: a member sees a teacher's
attachment from the moment its post goes live, and a teacher sees a student's file only while the
student is an active member **and** only once the work is turned in — the draft rule, applied to
files. `subfile_teacher_read` spells out both conditions rather than leaning on
`submission_teacher_read` through a subquery, so a later change to that policy cannot widen this one
by accident (the B18 lesson). No INSERT or UPDATE policy exists on either table, and no write grant
but the owner's DELETE on `material_attachment`.

The class chat (`20261005130000`) is the one classroom table a student writes directly: a
column-limited `INSERT` that `space_message_insert` holds to the caller and to
`app.can_post_message`. There is no UPDATE or DELETE policy and no such grant, so a message is never
edited and never really deleted — a moderator's deletion is a stamp, written by a function. A
member's read stops at that stamp; the teacher's does not.

### Assessment

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `past_paper` | `past_paper_read` | SELECT | `cuid() IS NOT NULL` | — | `20260801120100:310` |
| `past_paper` | `past_paper_admin` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:312` |
| `question` | `question_read` | SELECT | `cuid() IS NOT NULL` | — | `20260801120100:315` |
| `question` | `question_admin` | ALL | `app.is_admin()` | `app.is_admin()` | `20260801120100:317` |
| `question_slo` | `question_slo_read` | SELECT | `cuid() IS NOT NULL` | — | `20260801120100:320` |
| `item_difficulty` | `item_difficulty_read` | SELECT | `cuid() IS NOT NULL` | — | `20260801120100:322` |
| `slo_frequency_cluster` | `slo_freq_read` | SELECT | `cuid() IS NOT NULL` | — | `20260801120100:324` |
| **`question_key`** | *(none — deliberate)* | — | — | — | `20260801120100:327-332` |
| `quiz` | `quiz_read` | SELECT | `created_by = cuid() OR (space_id IS NOT NULL AND app.is_enrolled_in(space_id)) OR app.is_admin()` | — | `20260801120100:334` |
| `quiz` | `quiz_teacher_write` | ALL | `created_by = cuid()` | `created_by = cuid()` | `20260801120100:342` |
| `quiz_question` | `quiz_question_read` | SELECT | `EXISTS (SELECT 1 FROM public.quiz q WHERE q.id = quiz_id)` | — | `20260801120100:347` |
| `quiz_attempt` | `attempt_student_own` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:351` |
| `quiz_attempt` | `attempt_teacher_read` | SELECT | `EXISTS (SELECT 1 FROM public.quiz q WHERE q.id = quiz_id AND q.space_id IS NOT NULL AND app.owns_space(q.space_id)) OR app.is_admin()` | — | `20260801120100:357` |
| `attempt_answer` | `attempt_answer_owner` | ALL | `EXISTS (SELECT 1 FROM public.quiz_attempt a WHERE a.id = attempt_id AND a.student_id = cuid())` | same expression | `20260801120100:367` |
| `attempt_answer` | `attempt_answer_teacher_read` | SELECT | `EXISTS (SELECT 1 FROM public.quiz_attempt a JOIN public.quiz q ON q.id = a.quiz_id WHERE a.id = attempt_id AND q.space_id IS NOT NULL AND app.owns_space(q.space_id))` | — | `20260801120100:378` |

### Learner analytics

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `mastery_estimate` | `mastery_owner` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:392` |
| `mastery_estimate` | `mastery_guardian_read` | SELECT | `app.is_verified_guardian_of(student_id) OR app.is_admin()` | — | `20260801120100:397` |
| `coverage_record` | `coverage_owner` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:401` |
| `coverage_record` | `coverage_viewers_read` | SELECT | `app.is_verified_guardian_of(student_id) OR app.teaches_student_subject(student_id, subject_id) OR app.is_admin()` | — | `20260801120100:406` |
| `exam_readiness_score` | `readiness_owner` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:414` |
| `exam_readiness_score` | `readiness_viewers_read` | SELECT | `app.is_verified_guardian_of(student_id) OR app.teaches_student_subject(student_id, subject_id) OR app.is_admin()` | — | `20260801120100:419` |
| `review_schedule` | `review_owner` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:427` |

### Tutor sessions — owner-only, no exceptions

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `chat_session` | `chat_session_owner` | ALL | `student_id = cuid()` | `student_id = cuid()` | `20260801120100:438` |
| `message` | `message_owner` | ALL | `EXISTS (SELECT 1 FROM public.chat_session s WHERE s.id = session_id AND s.student_id = cuid())` | same expression | `20260801120100:443` |
| `visual_aid` | `visual_aid_owner` | ALL | `EXISTS (SELECT 1 FROM public.message m JOIN public.chat_session s ON s.id = m.session_id WHERE m.id = message_id AND s.student_id = cuid())` | same expression | `20260801120100:454` |

### Security and operations

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `agent_component` | `component_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:471` |
| `permission_manifest` | `manifest_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:473` |
| `agent_sbom_entry` | `sbom_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:475` |
| `vetting_result` | `vetting_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:477` |
| `audit_log` | `audit_insert` | INSERT | — | `true` | `20260801120100:482` |
| `audit_log` | `audit_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:484` |
| `api_request_log` | `reqlog_insert` | INSERT | — | `true` | `20260801120100:488` |
| `api_request_log` | `reqlog_admin_read` | SELECT | `app.is_admin()` | — | `20260801120100:490` |
| `audit_log_default` | *(none — deliberate)* | — | — | — | RLS enabled + forced at `20260802150000:35-36` |
| `api_request_log_default` | *(none — deliberate)* | — | — | — | RLS enabled + forced at `20260802150000:37-38` |

### Subscription and social identity

| Table | Policy | FOR | USING | WITH CHECK | Live at |
|---|---|---|---|---|---|
| `subscription_plan` | `subscription_plan_read` | SELECT | `cuid() IS NOT NULL` | — | `20260802120000:144` |
| `subscription_plan` | `subscription_plan_admin_write` | ALL | `app.is_admin()` | `app.is_admin()` | `20260802120000:148` |
| `subscription` | `subscription_owner` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260802120000:157` |
| `subscription` | `subscription_admin_read` | SELECT | `app.is_admin()` | — | `20260802120000:165` |
| `oauth_identity` | `oauth_identity_owner` | ALL | `user_id = cuid()` | `user_id = cuid()` | `20260802120000:172` |

`subscription_admin_read` is `SELECT`, not `ALL`, on purpose (`20260802120000:162-164`): an
administrator must not be able to silently grant anyone a paid subscription outside the payment
path.

### Objects with no policy

| Object | Why |
|---|---|
| `question_key` | **Deliberate and permanent.** See the invariants below. |
| `audit_log_default` | Deliberate. RLS is enabled and forced with no policy, making *direct* access default-deny while parent-routed reads and writes keep using `audit_log`'s own policies. |
| `api_request_log_default` | As above. |
| `storage.objects` (bucket `classroom-files`) | **Deliberate.** The bucket is private and no `storage.objects` policy is created: users are not Supabase Auth users, and only the backend — with storage-only S3 keys — reads or writes an object. Who may download a file is decided by the two file tables' policies above, before the object is opened. |
| `two_factor_status_v` | **Resolved 2026-08-16.** A view cannot carry row-level security — policies attach to tables. `20260816150000` set `security_invoker = true`, so it executes as its **caller** and the policies underneath apply. Was finding [B1](#b-known-gaps--the-database-would-not-catch-a-missed-check). `tests/integration/test_rls_coverage.py` now fails if any view in `public` lacks the option. |

---

## The `app.*` privileged functions

**72 live** (shadow and live agree, 2026-10-05), from 73 distinct names
ever defined — `app.issue_token_for_email` was dropped as a byte-for-byte duplicate of `app.insert_auth_token` (`20260803160000:151-153`).

All are in the `app` schema. All but two are `SECURITY DEFINER`; all but one carry
`SET search_path = public, pg_temp`, which is what prevents a shadowing attack from redirecting an
unqualified name inside the body. None takes dynamic SQL, and every query in the codebase uses
bound parameters.

### Row-Level Security helpers — called by policies, not by routes

These are the ones the policy predicates above call. They are `SECURITY DEFINER` so that reading
the tables they check does not recurse into the very policies calling them. **None is executable
by `PUBLIC`** — finding C5 was closed by `20260816190000`, and every helper since is granted to
`app_backend` explicitly, because a policy is evaluated with the privileges of the role running
the query: without `EXECUTE` it would error rather than deny.

| Function | Volatility | Definer? | Returns | Grant | Defined at |
|---|---|---|---|---|---|
| `app.current_user_id()` | `STABLE` | **No** | `uuid` — the bound user, or `NULL` | `app_backend` | `20260801120100:49` |
| `app.is_admin()` | `STABLE` | Yes | `boolean` — caller is an `active` `admin` | `app_backend` | `20260801120100:56` |
| `app.is_verified_guardian_of(p_student uuid)` | `STABLE` | Yes | `boolean` — a **verified** link exists | `app_backend` | `20260801120100:67` |
| `app.teaches_student_subject(p_student uuid, p_subject uuid)` | `STABLE` | Yes | `boolean` — active enrolment in a space the caller owns **and** an **unrevoked** `teacher_subject_scope` row | `app_backend` | `20260801120100:81`, body replaced `20261004120000` §1 |
| `app.owns_space(p_space uuid)` | `STABLE` | Yes | `boolean` — owner **and** active teacher **and** unrevoked scope for the space's subject (**B11**) | `app_backend` | `20260801120100:99`, body replaced `20261004120000` §1 |
| `app.is_enrolled_in(p_space uuid)` | `STABLE` | Yes | `boolean` — enrolled and `left_at IS NULL` | `app_backend` | `20260801120100:109` |
| `app.owns_active_space(p_space uuid)` | `STABLE` | Yes | `boolean` — `owns_space` **and** `status = 'active'`: the write predicate, so an archived classroom is read-only | `app_backend` | `20261004120000` §1 |
| `app.my_owned_space_ids()` | `STABLE` | Yes | `SETOF uuid` — spaces the caller owns with live scope | `app_backend` | `20261004120000` §1 |
| `app.my_member_space_ids()` | `STABLE` | Yes | `SETOF uuid` — spaces the caller is actively enrolled in | `app_backend` | `20261004120000` §1 |
| `app.caller_passes_guardian_gate()` | `STABLE` | Yes | `boolean` — `gate.py` in SQL; **fails closed** on an unbound user or unknown class level | `app_backend` | `20261004120000` §1 |
| `app.my_taught_students()` | `STABLE` | Yes | `TABLE (space_id, student_id)` — active members of the caller's scoped spaces | `app_backend` | `20261004140000:167` |
| `app.points_compatible(p_assignment uuid, p_points smallint)` | `STABLE` | Yes | `boolean` — the caller owns the classroom **and** no grade exceeds `p_points`; false for anyone else, so it is not an oracle | `app_backend` | `20261004140000:181` |
| `app.material_parent_published(p_announcement uuid, p_assignment uuid)` | `STABLE` | Yes | `boolean` — the attachment's post is live (`publish_at <= now()`) | `app_backend` | `20261004150000:122` |

**Why two set-returning helpers.** A `SECURITY DEFINER` function is never inlined, so a per-row
helper such as `app.owns_space(space_id)` runs once per **row**. Used as
`space_id IN (SELECT app.my_owned_space_ids())` it is an uncorrelated subquery that runs once per
**query** as a hashed subplan — the difference between a 300-row roster costing 300 lookups and one.
New classroom read policies use the set form; the single-space form stays for function bodies and
service pre-checks.

`app.is_verified_guardian_of` and `app.teaches_student_subject` were checked in the Epic 1 review
and **cannot be abused through their parameters** — both anchor on `app.current_user_id()`
internally, so passing an arbitrary student identifier proves nothing.

### Classroom — `POST /api/spaces` functions

`20261004120100`. Since `20261004120000` these are the **only** writers of `enrollment` and
`join_code` and the only way to create a `classroom_space`. Each derives the actor from
`app.current_user_id()` — never a parameter (finding C1's shape) — and **returns an outcome instead
of raising**, because a `RAISE` would surface as `500 INTERNAL_ERROR`. Capacity checks run after a
row lock (`FOR UPDATE` on `teacher_profile`, `FOR NO KEY UPDATE` on the space), so two concurrent
requests cannot both pass a limit. All are granted to `app_backend` and `REVOKE`d from `PUBLIC`.

| Function | Calling endpoint | Outcomes | Notes |
|---|---|---|---|
| `app.create_space(p_title text, p_subject uuid) → (outcome, new_space_id)` | `POST /api/spaces` | `created` · `not_teacher` · `unknown_subject` · `classroom_limit` · `scope_revoked` | Self-declares `teacher_subject_scope` in the same transaction; 50 active classrooms per teacher. |
| `app.rotate_join_code(p_space uuid, p_code text) → (outcome, new_code)` | `POST /api/spaces`, `POST /api/spaces/{id}/join-code` | `rotated` · `forbidden` · `collision` | The code is minted in Python (`secrets`); `collision` means retry with a fresh one. Requires a non-archived space. |
| `app.disable_join_code(p_space uuid) → boolean` | `POST /api/spaces/{id}/join-code` | — | Owner-only; allowed on an archived space. |
| `app.join_space_by_code(p_code text) → (outcome, joined_space_id, space_title, space_subject, space_board, space_class_level)` | `POST /api/spaces/join` | `joined` · `already_member` · `invalid_code` · `class_mismatch` · `classroom_full` · `gate_pending` · `not_student` | Normalises case, spaces and dashes. **A removed student gets `invalid_code`**, indistinguishable from an unknown code. Board, class **and** group must match. Re-checks the guardian gate. 300 active members per space. |
| `app.leave_space(p_space uuid) → boolean` | `DELETE /api/spaces/{id}/membership` | — | Idempotent; allowed on an archived space (leaving is a consent right, `prd.md:258`). |
| `app.remove_student(p_space uuid, p_student uuid) → boolean` | `DELETE /api/spaces/{id}/members/{student_id}` | — | Sets `left_at` and `removed_at`. |
| `app.space_people(p_space uuid) → (user_id, full_name, is_owner, joined_at, muted)` | `GET /api/spaces/{id}/people` | — | The narrow door past `app_user_self_read`: owner and **active** members only, `full_name` only; `muted` is shown to the owner only. |
| `app.my_spaces() → (space_id, title, status, subject…, owner_name, viewer_role, can_manage, member_count, joined_at)` | `GET /api/spaces`, `GET /api/spaces/{id}` | — | `member_count` for the owner only. A de-scoped teacher still sees their row with `can_manage = false`. |

Proved on a shadow database built from all 27 files (2026-10-04): the same attack script, run as
`app_backend`, **succeeds** against the 25 earlier migrations (a student creates a "teacher" space;
a student enrols without a code) and is refused with `permission denied` after these two.
`backend/tests/integration/test_classroom_rls.py` pins every row of the table above (44 tests; 52 with classroom Phase 3's `TestAnnouncementBoundary`).

### Classroom — assignment functions

`20261004140000` (classroom Phase 4). The **only** writers of `assignment_submission` and
`submission_grade`, and the only way to delete an assignment. Same contract as the space
functions above: the actor comes from `app.current_user_id()`, an outcome is returned rather than
raised, and each is `REVOKE`d from `PUBLIC`. Every submission and grade write takes
`app.lock_submission` — one advisory lock per (assignment, student) — so a grade saved while the
student edits or turns in cannot leave edited work behind a grade. **Once any grade row exists the
work is locked** ("editable until graded", `prd.md` CL-7), even before it is returned.

| Function | Calling endpoint | Outcomes | Notes |
|---|---|---|---|
| `app.save_submission_draft(p_assignment uuid, p_body text, p_link text) → text` | `PUT /api/assignments/{id}/submission` | `saved` · `forbidden` · `graded` · `turned_in` | Upsert while not turned in. `turned_in` means unsubmit first. `20261004140000:281` |
| `app.turn_in_submission(p_assignment uuid) → text` | `POST …/submission/turn-in` | `turned_in` · `already_turned_in` · `forbidden` · `graded` | Stamps `clock_timestamp()` — the real moment, unforgeable (no grant on the column). An empty turn-in is "mark as done". `20261004140000:306` |
| `app.unsubmit_submission(p_assignment uuid) → text` | `POST …/submission/unsubmit` | `unsubmitted` · `not_turned_in` · `forbidden` · `graded` | `20261004140000:333` |
| `app.save_grade(p_assignment, p_student, p_grade numeric, p_feedback text, p_return boolean) → text` | `PUT /api/assignments/{id}/grades/{student_id}` | `saved` · `forbidden` · `invalid_grade` | Owner of an **active** classroom, **active** member only; `0 ≤ grade ≤ points` (no points = feedback only). Takes `FOR SHARE` on the assignment so a concurrent change to `points` cannot interleave. Returning is one-way. `20261004140000:355` |
| `app.delete_assignment(p_assignment uuid) → (deleted, object_keys)` | `DELETE /api/assignments/{id}` | — | Owner of an active classroom. Since `20261004150000:321` (same signature, so `CREATE OR REPLACE` kept the grant) `object_keys` is every stored key the cascade is about to orphan — teacher attachments and **every** student's files, drafts and students who left included, none of which the teacher can read under RLS. `20261004140000:397` |

Two **internal** helpers carry **no grant to `app_backend` at all** (plan R9) — they are called only from
the functions above, which run as their owner: `app.submittable_space(p_assignment)` (published, active
classroom, active member, **guardian gate passed** — the Class 9–10 rule at the database too, not only
on the route; `20261004140000:202`) and `app.lock_submission(p_assignment, p_student)` (`20261004140000:220`). Calling
either as `app_backend` is `permission denied`, which `test_classroom_rls.py` asserts.
`TestAssignmentBoundary` (17 tests) pins every row of this section.

### Classroom — file and link functions

`20261004150000` (classroom Phase 6). The **only** writers of `submission_file` and the only way to
add a `material_attachment`. Each takes the **full object key**, already stored by the backend —
the object goes first and the row second, so no lock is held across an upload, and on any outcome
but `added` the backend deletes the object it just stored. The key's prefix is then held to the
caller by the table's CHECK constraint, not by the function. Quotas run under
`app.lock_space_files` — one advisory lock per classroom — so two parallel uploads cannot both pass
a limit.

| Function | Calling endpoint | Outcomes | Notes |
|---|---|---|---|
| `app.add_submission_file(p_assignment, p_object_key, p_filename, p_content_type, p_size, p_sha256) → (outcome, new_file_id)` | `POST /api/assignments/{id}/submission/files` | `added` · `forbidden` · `graded` · `turned_in` · `too_many_files` · `submission_quota` · `classroom_quota` | Same gate as a draft (`app.submittable_space`, guardian gate included) and the same `app.lock_submission`; creates the draft row if there is none. 5 files and 20 MiB per submission, 2 GiB per classroom. `20261004150000:191` |
| `app.remove_submission_file(p_file uuid) → (outcome, removed_object_key)` | `DELETE /api/submission-files/{id}` | `removed` · `forbidden` · `graded` · `turned_in` | The caller's own file only; the key comes back for deletion **after** commit. `20261004150000:241` |
| `app.add_material_attachment(p_announcement, p_assignment, p_object_key, …) → (outcome, new_file_id)` | `POST /api/announcements/{id}/attachments`, `POST /api/assignments/{id}/attachments` | `added` · `forbidden` · `too_many_files` · `classroom_quota` | Exactly one parent; owner of an **active** classroom. 10 files per post, 2 GiB per classroom. `20261004150000:271` |
| `app.add_submission_link(p_assignment uuid, p_url text) → (outcome, new_link_id)` | `POST /api/assignments/{id}/submission/links` | `added` · `forbidden` · `invalid_url` · `graded` · `turned_in` · `too_many_links` | Classroom Phase 6b. The file's gate and lock; checks the URL itself (a CHECK violation would be a 500); the same link twice returns the existing row. 5 links per submission. Stamps `clock_timestamp()`, so links list in the order added. `20261005120000:72` |
| `app.remove_submission_link(p_link uuid) → text` | `DELETE /api/submission-links/{id}` | `removed` · `forbidden` · `graded` · `turned_in` | The caller's own link, while the work is an ungraded draft. `20261005120000:121` |

Two more **internal** helpers with **no grant** (plan R9): `app.space_storage_bytes(p_space)`
(`20261004150000:134`, the 2 GiB sum) and `app.lock_space_files(p_space)` (`20261004150000:146`). A teacher removes
an attachment with a plain `DELETE … RETURNING object_key` under `material_owner_delete`; the
object follows after commit. `TestFileBoundary` (10 tests, `test_classroom_rls.py`) pins this
section: no direct write, a forged key refused, the draft and leaving rules, a scheduled post's
attachment, the sixth file, the locks after turn-in and grading, the helpers' missing grant, and
`delete_assignment` returning the keys of a student who left. `TestLinkBoundary` (9 tests) pins the
link rows the same way: no direct write, https only, the draft and leaving rules, a classmate sees
nothing, one row for a repeated link and a refused sixth, the locks, no link on a scheduled
assignment, and the cascade with the assignment.

**The single link moved** (`20261005120000:162-168`): under the migration role, which bypasses RLS (as
`20260817120000`'s top-level `UPDATE` of `auth_token` did — the live role reports
`rolbypassrls`), every `link_url` is copied into `submission_link` and then cleared, so a re-run
copies nothing. Proved on the shadow with a seeded old-style link; the live database held none
(2026-10-05).

**The bucket.** `20261004150000:387` inserts `classroom-files` into `storage.buckets` — private, 9 MiB,
the same five types — so it is not a dashboard step that exists in one environment and no
migration (finding F1's lesson). It is skipped where there is no `storage` schema (a plain
PostgreSQL shadow), and if the migration role lacks the privilege it raises a **WARNING**, not an
error: the bucket must then be created by hand with those settings. On the live project the
migration created it (2026-10-05: private, 9 437 184 bytes, 5 types).

### Classroom — chat functions

`20261005130000` (classroom Phase 7). Posting is a column-limited `INSERT` under
`space_message_insert`; these are the predicate it calls, the only writers of moderation state, and
the one door through which a member learns that a message they can no longer read was deleted.

| Function | Calling endpoint | Outcomes | Notes |
|---|---|---|---|
| `app.can_post_message(p_space uuid) → boolean` | the `space_message_insert` policy; `GET` and `POST /api/spaces/{id}/messages` | `true` · `false` | Active classroom; its teacher (`app.owns_space`) always, even while locked; otherwise an unlocked chat and an active, **unmuted** member who passes `app.caller_passes_guardian_gate()` — the Class 9–10 rule at the database. Fails closed: no such classroom is `false`. **Granted**, because a policy calls it. `20261005130000:89` |
| `app.delete_space_message(p_message uuid) → text` | `DELETE /api/messages/{id}` | `deleted` · `already_deleted` · `forbidden` | The classroom's teacher only. Stamps `deleted_at` (`clock_timestamp()`) and `deleted_by`; the row is retained. Works on an archived classroom — moderation does not stop when posting does. Deleting twice is `already_deleted`, not an error. `20261005130000:137` |
| `app.set_student_muted(p_space uuid, p_student uuid, p_muted boolean) → boolean` | `PUT /api/spaces/{id}/members/{student_id}/mute` | `true` · `false` | The classroom's teacher only, and an **active** member only. Keeps the first mute's time; unmuting clears it. A mute survives leaving and rejoining (`app.join_space_by_code` leaves `muted_at` alone). `20261005130000:165` |
| `app.space_message_tombstones(p_space uuid, p_since timestamptz) → (message_id)` | `GET /api/spaces/{id}/messages` | ids | Messages deleted since a time — **ids only, never content** — for the classroom's teacher and current members, because a member cannot read a deleted row at all. `20261005130000:184` |

`TestChatBoundary` (16 tests, `test_classroom_rls.py`) pins this section: the class reads what a
member and the teacher post; nobody posts as someone else; the time and the moderation columns are
not insertable, and no row is updated or deleted directly; an outsider and a student who left
neither read nor post; a muted student reads but cannot post, and the mute survives leaving and
rejoining; only the owning teacher mutes, and only a current member; a locked chat takes posts from
its teacher only, and a student cannot lock it; an archived classroom takes no posts but is still
moderated; a Class 9 student whose guardian withdrew consent cannot post; a deleted message is hidden
from the class and kept for the teacher; only the owning teacher deletes; and tombstones reach the
class and nobody else.

### Classroom — the parent's overview

`20261005140000` (classroom Phase 8, `prd.md` CL-10). A parent has **no read policy on any
classroom table**; this one function is their whole view.

| Function | Calling endpoint | Returns | Notes |
|---|---|---|---|
| `app.guardian_classroom_overview() → (student_id, student_name, space_id, space_title, space_status, subject_name, teacher_name, assignment_id, assignment_title, due_at, points, turned_in_at, grade, returned_at)` | `GET /api/parent/classrooms` | one row per child × classroom × assignment | **No parameters**: the parent is `app.current_user_id()` (the `change_password` pattern), so it cannot be aimed at another family. Verified links only; an active student account; the child's **current** classrooms (one they left drops out; an archived one stays, with its status); published assignments due in the last 120 days or undated; `grade` only once `returned_at` is set. A verified child in no classroom is one row with the classroom columns `NULL`. Never feedback, the work, files, links, the chat or a classmate. `20261005140000:29` |

`TestParentOverview` (10 tests, `test_classroom_rls.py`) pins it: a verified parent sees the
classroom, its teacher and its classwork; the result has exactly these columns and no classmate; a
grade appears only once returned; scheduled and long-past assignments are left out; an archived
classroom stays labelled; a pending or revoked link shows nothing; another family sees none of
this child; a teacher or a student gets no row; a classroom the child left drops out while the
child stays; and a parent reads **no** classroom table directly — not the classroom, the roster,
the stream, the assignments, the work, the grades, the files, the links or the chat.

### The trigger function

| Function | Volatility | Definer? | Returns | Grant | Defined at |
|---|---|---|---|---|---|
| `app.set_updated_at()` | default `VOLATILE` | No | `trigger` — sets `NEW.updated_at = now()` | `app_backend` (`20260816190000`) | `20260801120000:85` |

**17** `CREATE TRIGGER` statements (`grep -hE '^CREATE TRIGGER' supabase/migrations/*.sql | wc -l`,
re-measured 2026-10-04). The profile tables that once carried `updated_at` with no trigger
(finding D14) were closed by `20260817150000` — see the section below.

### Session and token lifecycle — `POST /auth/login`, `/auth/refresh`, `/auth/logout`

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.lookup_user_for_login(p_email text)` | `STABLE` | Yes | `TABLE(id, password_hash, status, email_verified_at, role)` — deliberately not `SELECT *`. **`role` was added by `20260816140000`** so `login()` can decide which of the two sign-in endpoints an account may use (FR-A2a) inside the query it was already making, rather than as a second round trip on the hot login path | `backend/app/auth/service.py:305-313` (`login`, `:278`) → `POST /auth/login` (`routes.py:104`) and `POST /auth/admin/login` (`routes.py:115`) | `app_backend` | `20260816140000:57` (originally `20260802140000:115`) |
| `app.lookup_2fa_for_login(p_user_id uuid)` | `STABLE` | Yes | `TABLE(method, status, locked_until)` — no secret, no counter | `service.py:324` (`login`) → `POST /auth/login` | `app_backend` | `20260803180000:36` |
| `app.lookup_refresh_token(p_token_hash text)` | `STABLE` | Yes | `TABLE(id, user_id, kind, revoked, expires_at)`; takes a hash, never a plaintext token | `backend/app/auth/tokens.py:80` (`find_token`, `:76`) → `POST /auth/refresh` (`routes.py:109`) | `app_backend` | `20260802140000:133` |
| `app.insert_auth_token(p_user_id uuid, p_kind token_kind, p_token_hash text, p_expires_at timestamptz)` | `VOLATILE` | Yes | `uuid` | `tokens.py:54` (`_insert_token`, `:50`) — every token-issuing path | `app_backend` | `20260802140000:182` |
| `app.revoke_auth_token(p_id uuid)` | `VOLATILE` | Yes | `void` | `tokens.py:119` (`rotate_refresh_token`, `:98`) | `app_backend` | `20260802140000:152` |
| `app.revoke_refresh_family(p_user_id uuid)` | `VOLATILE` | Yes | `integer` — how many were revoked, so the caller can audit it | `tokens.py:134` (`revoke_refresh_family`, `:125`) — reuse-detection breach response | `app_backend` | `20260802140000:163` |

### `updated_at` is maintained on every table that has it — Phase 5 (`20260817150000`)

`app.set_updated_at()` existed and nine tables used it. **Four carried the column with no trigger**,
so the value was written once by its `DEFAULT now()` and never changed again — a column that reports
creation time while looking exactly like the nine that report modification time.

⚠️ **The register named three; the live catalogue had four.** Reading `initial_schema.sql` finds
`teacher_profile`, `parent_profile` and `admin_profile`, which are adjacent in the file. Querying
`pg_class`/`pg_trigger` adds **`mastery_estimate`**, declared 400 lines away — and it is the one
with consequences, being one of the five progress tables a parent and a teacher read. Finding F1's
lesson again: author from the catalogue, never from the migration files.

⚠️ `app.set_updated_at()` had its `PUBLIC` execute revoked by `20260816190000` (C5). PostgreSQL
checks `EXECUTE` on a trigger function **when the trigger is created**, not when it fires, so these
must be applied as the owner — which is how migrations run, but not how an `app_backend` session
would.

⚠️ The trigger function uses `now()`, and that is correct here, unlike everywhere in Phase 4.
`updated_at` records which TRANSACTION last touched the row, so rows written together sharing a
timestamp is the intent; `clock_timestamp()` would make them disagree.

### Session policy — Phase 4 (`20260817120000`, `20260817130000`)

**Four columns and three functions that give a session an end.** Before them,
revoking refresh tokens ended only the ability to obtain a NEW access token — the one already in the
caller's memory stayed valid for up to `access_token_ttl_minutes`, so a password change left an
attacker signed in for another quarter of an hour.

| Column | On | Why |
|---|---|---|
| `sessions_invalidated_at` | `app_user` | Every access token issued at or before this instant is refused |
| `family_started_at` | `auth_token` | When a rotating chain BEGAN. Carried forward across every rotation, so it bounds the chain absolutely rather than per token |
| `revoked_at` | `auth_token` | Tells a two-tab RACE from a token THEFT |
| `revoked_reason` | `auth_token` | `reuse_detected`, `password_change`, `password_reset`, `family_expired`, `rotated`. **NULL means an ordinary logout**, which is the common case |

| Function | Volatility | Definer? | Returns | Grant |
|---|---|---|---|---|
| `app.invalidate_sessions(p_user_id uuid)` | `VOLATILE` | Yes | `timestamptz` — the stamp it wrote | ⚠️ **owner only** |
| `app.insert_refresh_token(uuid, text, timestamptz)` | `VOLATILE` | Yes | `uuid` | `app_backend` |
| `app.rotate_refresh_token(text, text, timestamptz, interval, interval)` | `VOLATILE` | Yes | `TABLE(outcome, token_user_id, family_started_at)` | `app_backend` |
| `app.purge_expired_auth_tokens(interval)` | `VOLATILE` | Yes | `integer` | ⚠️ **owner only** (`20260817140000`) |

⚠️ **`clock_timestamp()`, NEVER `now()`, everywhere in this phase.** `now()` is
`transaction_timestamp()` and is frozen for the whole transaction — measured on this project at
**0.00s of movement across 2 real seconds**, against **2.20s** for `clock_timestamp()`. A stamp
written with `now()` lands at the transaction's START, so a token minted later in the same
transaction survives the invalidation meant to kill it. The integration suite runs inside one outer
transaction, so such a test would PASS while asserting nothing.

⚠️ **`app.invalidate_sessions` is not granted to `app_backend`, and neither is the purge.** Both take
a subject or delete audit-relevant rows; a grant would let any authenticated caller sign another user
out or erase evidence. Only the owner executes them, which means only the SECURITY DEFINER functions
that call them can. Same reasoning that made `app.change_password` take no user identifier at all.

⚠️ **UPDATE on `auth_token` is narrowed to `revoked`.** §2.3 split this table's `FOR ALL` policy into
`FOR SELECT` plus `FOR UPDATE ... WITH CHECK (revoked = true)`, but left the UPDATE grant table-wide
— so the moment these columns existed a caller could author their own `revoked_reason` or rewrite
`family_started_at` and defeat the cap. `revoke_user_tokens` (logout) is the only plain UPDATE in the
application and names `revoked` alone.

⚠️ **THE CLOCKS ARE ON DIFFERENT MACHINES, AND THIS ALMOST SHIPPED BROKEN.** A token's `iat` is minted
by Python on the application host; `sessions_invalidated_at` is stamped by `clock_timestamp()` on the
database host. **Measured while building this**: a token created BEFORE a password change carried
`iat = 20:03:43` while the stamp written afterwards read `20:03:41.88` — the database ran 1.1s behind,
so the token looked as though it had been issued after its own invalidation and sailed through.
Nothing failed; the feature was simply inert. A JWT `iat` is an integer besides, so there is no
sub-second precision to fall back on. `security.session_is_invalidated` therefore compares `<=`
against a cutoff widened by `session_invalidation_skew_seconds` (default 5), which fails CLOSED: a
token issued shortly AFTER an invalidation is also refused, costing one extra sign-in. Pinned by
`tests/integration/test_session_policy.py`.

#### The rotation race — finding D2

`app.rotate_refresh_token` replaces four unlocked round trips (read, check `revoked`, revoke, insert)
with one statement holding a `FOR UPDATE` lock. Two concurrent refreshes could previously BOTH pass
the check: one forked the family, defeating any cap, and the other tripped reuse detection on a
legitimate refresh.

⚠️ **A lock alone does not finish the job.** It stops the fork; the loser still finds `revoked = true`.
Reuse detection revokes the whole family, so a user with two browser tabs — the client's single-flight
guard is per TAB — was signed out of every device on a collision they could not avoid. The function
therefore reports `raced` instead of `reuse` when the revocation is inside `p_race_grace` **and** a
live sibling of the same family still exists. Both conditions are required, and both directions are
tested.

⚠️ **The cost, written down rather than glossed:** a thief replaying a stolen token inside that window
also lands on the race path, so the family is not revoked. They are still refused, and `refresh()`
writes a `refresh_token_race_detected` audit row so the event is not silent. A replay two seconds
after a legitimate rotation is genuinely indistinguishable from a second tab.

#### Retention — `20260817140000`

`app.purge_expired_auth_tokens(p_grace interval DEFAULT '30 days')` deletes rows more than the grace
period **past expiry**. ⚠️ The grace is not tidiness: `rotate_refresh_token` checks `revoked` BEFORE
`expires_at`, so a stolen token replayed after expiry is still reported as theft — **but only while
its row exists**. Purging on expiry alone turns that replay into a silent 401. `pg_cron` is available
on this project but **not installed**, so the migration creates the function and skips scheduling;
enable the extension and re-apply to register the daily job.

### Account management — `/auth/password/change` (FR-A8)

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.change_password(p_new_password_hash text)` | `VOLATILE` | Yes | `TABLE(changed boolean, tokens_revoked integer)` | `backend/app/auth/service.py` (`change_password`) → `POST /auth/password/change` | `app_backend` | `20260816210000` |

⚠️ **It takes no user identifier, and that is the whole design.** Every other `SECURITY DEFINER`
function here accepts the user it should act on. This one derives its subject from
`app.current_user_id()`, which `authenticated` bound — so the shape of finding **C1** ("accepts a
caller-chosen user") cannot exist here at all. The alternative, a `p_user_id` parameter guarded by
`p_user_id = app.current_user_id()`, works only for as long as nobody deletes the guard; there is no
guard to delete. This is possible **only because the endpoint is authenticated** — the
pre-authentication functions have no caller identity to derive from, which is why C1 needs a
redesign rather than a check.

⚠️ **Two return fields because one cannot carry the answer.** `tokens_revoked = 0` is a legitimate
success for a user with no live sessions, so the count cannot also mean "refused" — a caller writing
the natural `if not result:` would report success on a password that never changed. `changed`
answers the security question; `tokens_revoked` answers the audit one.

**Fail-closed at every exit**, and the session revocation runs *after* the password write is
confirmed to have hit a row, so a refusal can never log anybody out. Verifying the CURRENT password
stays in Python, where argon2 lives — `20260816160000` revoked `UPDATE` on `app_user` and never
`SELECT`, so `app_user_self_read` still serves the hash to its owner.

### Two-factor authentication — `/auth/2fa/*`

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.lookup_challenge_token(p_token_hash text, p_kind token_kind)` | `STABLE` | Yes | `TABLE(id, user_id, kind, revoked, expires_at)` | `service.py:703` (`two_factor_enroll`, `:688`), `service.py:785` (`two_factor_confirm`, `:773`) | `app_backend` | `20260803120000:43` |
| `app.upsert_2fa_enrollment(p_user_id uuid, p_method two_factor_method, p_secret_encrypted bytea)` | `VOLATILE` | Yes | `void` | `service.py:749`, `service.py:762` (`two_factor_enroll`) → `POST /auth/2fa/enroll` (`routes.py:166`) | `app_backend` | `20260803160000:44` (supersedes `20260803120000:76`) |
| `app.activate_2fa(p_user_id uuid, p_counter bigint DEFAULT NULL)` | `VOLATILE` | Yes | `void` | `service.py:856` (`two_factor_confirm`) → `POST /auth/2fa/confirm` (`routes.py:176`) | `app_backend` | `20260803160000:78` (supersedes the one-argument form at `20260803120000:109`) |
| `app.replace_backup_codes(p_user_id uuid, p_hashes text[])` | `VOLATILE` | Yes | `integer` — count inserted; atomic delete-then-insert, so the old set is gone the instant the new one exists | `service.py:863` (`two_factor_confirm`) | `app_backend` | `20260803120000:131` |
| `app.start_2fa_challenge(p_token_hash text, p_kind token_kind)` | `STABLE` | Yes | `TABLE(token_user_id, token_id, method, status, totp_secret_encrypted, last_used_counter, failed_attempts, locked_until)` | `service.py:907` (`two_factor_verify`, `:887`), `service.py:1028` (`two_factor_resend`, `:1017`) | `app_backend` | `20260803120000:166` |
| `app.verify_2fa_success(p_user_id uuid, p_counter bigint)` | `VOLATILE` | Yes | `void` — the **only** event that clears `failed_attempts` and `locked_until` | `service.py:994` (`two_factor_verify`) | `app_backend` | `20260803120000:203` |
| `app.verify_2fa_failure(p_user_id uuid, p_failed smallint, p_locked_until timestamptz)` | `VOLATILE` | Yes | `void` | `service.py:671` (`_record_2fa_failure`, `:657`) | `app_backend` | `20260803120000:229` |
| `app.consume_backup_code(p_user_id uuid, p_code_hash text)` | `VOLATILE` | Yes | `integer` — 1 or 0 | `service.py:982` (`two_factor_verify`) | `app_backend` | `20260803120000:255` |
| `app.get_unused_backup_codes(p_user_id uuid)` | `STABLE` | Yes | `TABLE(code_hash text)` — hashes only, never plaintext | `service.py:975` (`two_factor_verify`) | `app_backend` | `20260803120000:284` |
| `app.issue_email_otp(p_user_id uuid, p_token_hash text, p_expires_at timestamptz)` | `VOLATILE` | Yes | `uuid`; revokes every prior unrevoked one-time password first | `service.py:569` (`_issue_and_send_email_otp`, `:555`) | `app_backend` | `20260803120000:304` |
| `app.lookup_email_otp(p_user_id uuid, p_code_hash text)` | `STABLE` | Yes | `TABLE(id, user_id, expires_at)` | `service.py:840` (`two_factor_confirm`), `service.py:958` (`two_factor_verify`) | `app_backend` | `20260803120000:339` |

### Email verification and password reset

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.consume_token_and_verify_email(p_token_hash text)` | `VOLATILE` | Yes | `TABLE(user_id, already_verified)` — **idempotent**, so a link opened twice (mail-client prefetch) does not show an error | `service.py:1098` (`verify_email`, `:1086`) → `POST /auth/email/verify` (`routes.py:250`) | `app_backend` | `20260803120000:373` |
| `app.consume_password_reset_token(p_token_hash text, p_new_password_hash text)` | `VOLATILE` | Yes | `boolean`; also revokes **every** refresh token for the user — a password change kills every session | `service.py:1193` (`reset_password`, `:1181`) → `POST /auth/password/reset` (`routes.py:281`) | `app_backend` | `20260803120000:447` |
| `app.check_token_status(p_token_hash text, p_kind token_kind)` | `STABLE` | Yes | `TABLE(token_found, token_expired, token_revoked, token_user_id)` — distinguishes 410 `TOKEN_EXPIRED` from 400 `INVALID_TOKEN` | `service.py:601` (`_raise_for_token_status`, `:583`) | `app_backend` | `20260803160000:105` (supersedes `20260803120000:547`, which lacked `token_revoked`) |
| `app.lookup_user_for_email_flow(p_email text)` | `STABLE` | Yes | `TABLE(id, email, full_name, language_pref, email_verified_at, status)` — returns the **stored** address, so delivery never depends on the caller's spelling, plus the locale the templates need | `service.py:624` (`_lookup_for_email_flow`, `:612`) → `POST /auth/password/forgot` (`routes.py:271`), `POST /auth/email/resend` (`routes.py:261`) | `app_backend` | `20260803160000:131` |
| `app.lookup_user_email(p_user_id uuid)` | `STABLE` | Yes | `TABLE(email citext, full_name text)` | **No call site.** `grep -rn 'lookup_user_email' backend/app backend/tests` returns nothing — superseded in practice by `lookup_user_for_email_flow` | `app_backend` | `20260803120000:499` |

### Guardian gate — `/auth/guardian/*`

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.lookup_parent_id_by_email(p_email text)` | `STABLE` | Yes | `uuid` — only an **active** account whose `role = 'parent'` | `service.py:1236` (`guardian_invite`, `:1210`) → `POST /auth/guardian/invite` (`routes.py:302`) | `app_backend` | `20260802150000:133` |
| `app.reinvite_guardian_link(p_student uuid, p_parent uuid)` | `VOLATILE` | Yes | `guardian_status`, or `NULL` when nothing was reset so the caller can fail loudly. Hard guard `status <> 'verified'` | `service.py:1270` (`guardian_invite`) | `app_backend` | `20260803090000:87` |
| `app.lookup_guardian_parent_email(p_student uuid)` | `STABLE` | Yes | `text` — the representative parent email (verified wins, then latest `created_at`) | `service.py:1329` (`guardian_status`, `:1292`) → `GET /auth/guardian/status` (`routes.py:317`) | `app_backend` | `20260802150000:116` |
| `app.confirm_guardian_link(p_parent uuid, p_token_hash text)` | `VOLATILE` | Yes | `TABLE(status guardian_status, student_name text)` — the status **before** the transition, so the caller can tell 200 from 409 | `service.py:1357` (`guardian_confirm`, `:1344`) → `POST /auth/guardian/confirm` (`routes.py:331`) | `app_backend` | `20260802150000:75` |

`app.confirm_guardian_link` is a single statement built from four common table expressions. The
materialisation of `l` before the data-modifying `upd` runs is what guarantees the returned status
is the pre-update value (`20260802150000:72-74`), and the token is consumed only when a transition
actually happened, so the "already verified" path leaves it untouched.

---

## Invariants and the reason for each

### 1. `question_key` has no policy, and must never gain one

`question_key` (`20260801120000:404`) holds the answer keys. Row-Level Security is **enabled and
forced** on it by the blanket loop, and **no policy was ever written**. Under forced RLS a table
with no matching policy is deny-all, so `app_backend` cannot read a single row — no route, no
serializer, no accidental `SELECT *` can leak an answer key, because the database refuses before
the application is even consulted. Grading runs under the service role.

This is the database-level backstop for non-functional requirement NFR-8, *"answer keys never
leave the server"*. `20260801120100:327-332` states it, and `20260802140000:16-18` repeats the
warning while fixing six *other* policy-less tables: **"Do not 'fix' it here."** A future
contributor sweeping for tables without policies will find this one. It is correct as it stands.

### 2. `audit_log` is append-only from the application

`audit_insert` is `FOR INSERT WITH CHECK (true)` and `audit_admin_read` is `FOR SELECT`. There is
**no UPDATE and no DELETE policy**, so under forced RLS the trail cannot be edited or erased
through `app_backend` — only appended to, and read by administrators
(`20260801120100:480-485`). Tamper-resistance here is the *absence* of policies, not the presence
of one, which means it is silently destroyed by anyone who "helpfully" adds a `FOR ALL` policy to
tidy up.

### 3. A partitioned table needs Row-Level Security on the **default partition** too

The blanket enable loop at `20260801120100:126-137` filters `tablename NOT LIKE '%_default'`. That
left `audit_log_default` and `api_request_log_default` with **RLS disabled entirely**.
`ENABLE ROW LEVEL SECURITY` does not cascade to partitions and policies are per-table, so an
`app_backend` connection could run `SELECT * FROM public.audit_log_default` and read the whole
audit trail straight past `audit_admin_read`.

Fixed by `20260802150000:35-38`, which enables *and* forces RLS on both. Verified against
PostgreSQL 17 (`20260802150000:14-17`): a partition with RLS forced and no policies is default-deny
for **direct** access, while parent-routed inserts and selects keep using the parent's policies —
which is why writes still land and `audit_admin_read` still gates reads.

**Every future partition needs the same two `ALTER TABLE` statements.** Adding a monthly partition
without them reopens the hole.

### 4. Grants are table-wide, so Row-Level Security gives no column protection

`20260801120100:36-39` grants `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public` to
`app_backend`, plus `ALTER DEFAULT PRIVILEGES` for every table created later. RLS filters **rows**;
it has no opinion about columns. So wherever a policy allows a row, it allows *every column of that
row* — a design fact, not a bug, but the one that turns several `FOR ALL` policies below into real
privilege problems. Column-level protection requires column-level `GRANT`s, which do not exist here
yet.

This is also why the two-factor base tables carry no admin policy: giving administrators a row
would have given them `totp_secret_encrypted` (`20260801120100:214-218`). The view exists precisely
to avoid that.

### 5. Unset binding means zero rows, and zero rows looks like "nothing to see here"

Every owner-scoped policy compares against `app.current_user_id()`. When it is unset the comparison
is `NULL`, the policy matches nothing, and the query returns an **empty result with no error**.
`20260803180000` exists because exactly that happened in `login()`: a plain `SELECT` on
`two_factor_enrollment` before a session existed returned zero rows, which the code read as "no
second factor enrolled" — so a user with active Time-based One-Time Password was handed an
enrolment token, `/2fa/enroll` correctly refused, and the account became unreachable with a correct
password and a correct authenticator. The lockout check read the same empty result and never fired.

The lesson written into the schema: pre-authentication reads go through a **narrow
`SECURITY DEFINER` function**, never a plain query and never the RLS-bypassing connection.

### 6. Trial length lives in the database default, not the application

`subscription.trial_ends_at DEFAULT (now() + interval '14 days')` (`20260802120000:70`) is the
source of truth. The application must not carry its own copy of the number.

### 7. Absence of a subscription row is not `trialing`

Derive access fail-closed: no row means no access (`20260802120000:19-22`). A failed insert must
never silently grant free access forever.

### 8. Chat is owner-only

`chat_session`, `message` and `visual_aid` have exactly one policy each, all owner-scoped, with no
teacher, parent or admin path and no privileged function touching them. Re-verified in the Epic 1
review; **this invariant holds**.

⚠️ **Classroom chat is a different thing and must never reuse these tables.** The owner brought a
class-public classroom chat into v1 (2026-10-03); it is its own table, `space_message`
(`20261005130000`, classroom Phase 7), class-public by design, with teacher moderation — see
[invariant 13](#13-who-may-post-in-the-class-chat-is-the-insert-policy). Invariant 8 is about the
private **tutor** conversation and is unchanged by it.

### 9. Classroom membership and codes are written only by functions

Since `20261004120000`, `app_backend` holds **no** write grant on `enrollment` or `join_code`, no
INSERT or DELETE on `classroom_space`, and no DELETE on `teacher_subject_scope`. Every change goes
through a `SECURITY DEFINER` function that reads the actor from `app.current_user_id()`. **Do not
grant a write privilege back to make an endpoint easier** — add a narrow function, the same rule as
pre-authentication access (`backend/CLAUDE.md` §3). `test_classroom_rls.py` asserts each refusal by
its message.

### 10. Scheduled classroom content is hidden by the read policy, not by a job or the interface

Since `20261004130000`, a member reads an announcement only when `publish_at <= now()`. **There is no
publisher** — no background job, no status column; the post becomes visible because the predicate
starts to hold. So do not add a `published` flag (it would drift from the timestamp it summarises),
and do not filter scheduled rows in the service instead of the policy (a missed filter would leak a
post early, which is exactly what the second layer exists to stop). The owner's read policy has no
time condition, so the teacher sees their own scheduled posts. Assignments follow the same rule
(`assignment_member_read`, `20261004140000`), and a scheduled assignment cannot be submitted to either
(`app.submittable_space` requires `publish_at <= now()`).

### 11. A teacher-owned field on a student-owned row is its own table

Every application user connects as `app_backend`, so a column grant cannot tell a teacher from a
student. A grade stored as a column on `assignment_submission` would therefore be writable by the
student whose work it grades. That is why `submission_grade` is a separate table, why neither table
has any write grant, and why `submission_teacher_read` adds `turned_in_at IS NOT NULL`: the student
owns the draft until they hand it in. **Do not "simplify" the grade onto the submission row.** Status
(late, missing, graded) is likewise never stored — it is derived from three timestamps owned by two
people, and a stored copy would drift the first time a deadline moved.

### 12. A stored file is authorized by its row, and its key is held to its owner by the database

Since `20261004150000`, the bytes live in a private bucket that only the backend reaches; the tables
decide who may see each object, and a download is served only after its row has been read under
Row-Level Security. The object key **is** the storage boundary, so `ck_material_key` and
`ck_subfile_key` hold it to `s/<space>/…` and `u/<space>/<student>/…`: a service bug that passes
another student's key is a CHECK violation, not a leak. **Do not add a `storage.objects` policy, or
any link path that skips the row read**, and do not loosen either CHECK. The one link that exists
(classroom Phase 6b, `file_service.view_link`) is minted only **after** that read, for PDF and images
only, and lives five minutes: it is a bearer pass to one object, never stored or logged. Objects are stored before
their row and deleted only **after** the deleting transaction commits — so a rollback can orphan an
object, never a row (`backend/app/classroom/storage.py`).

### 13. Who may post in the class chat is the insert policy

Since `20261005130000`, every safeguard `prd.md` CL-5 requires of the class chat is a database fact:
`space_message_insert` calls `app.can_post_message`, so a muted student, a locked chat, an archived
classroom, a student who left and a Class 9–10 student without a verified guardian are each refused
by PostgreSQL, whatever the service does. The service asks the same function first only so that a
refusal is a reason the student can act on. A deletion is a stamp, never a `DELETE`: members stop
reading the row, the teacher keeps it for review. **Do not add an UPDATE or DELETE grant, a member
read path to deleted rows, or a second way to post.**

### 14. A parent reads the classroom through one function, never through a policy

Since `20261005140000`, a parent's whole view of a child's classrooms is
`app.guardian_classroom_overview()` — anchored on the caller, with no parameters. Row-Level Security
is per **row**: a parent read policy on `assignment_submission` or `submission_grade` would hand
over the student's answer and the teacher's private feedback along with the turn-in time and the
grade, and the service would be all that stood between them and the parent (`prd.md` CL-10 forbids
both). **Do not add a parent read policy to a classroom table**; add a column to the function
instead, if CL-10 ever allows one.

---

## Known gaps

Recorded here rather than deferred until fixed, per the Phase 0 honesty rules. These are findings
**B1–B19** of the 35-finding Epic 1 register.

### How to read this section

**These are defence-in-depth failures, not remote exploits.** Reaching any of them requires the
ability to run arbitrary SQL as `app_backend`, and every implemented route is narrow — 55 of the 83
specified endpoints exist, each issuing fixed statements with bound parameters. The Epic 1 review confirmed
that **no current route passes a request-controlled user identifier** into a privileged function.

What is false today is the promise in user-story card 1.5: *"each request checked by the
application and again by the database, so that a single missed check can never expose another
student's data."* The second layer does not hold. **The application layer is holding alone**, and
several of these go live the moment a matching endpoint ships — which is the argument for fixing
them before the endpoints arrive, not after.

Fixes are scheduled for Phase 2. See [`/Claude/HISTORY.md`](../../Claude/HISTORY.md) for the change
log and [`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md) for what must be updated when they
land.

### B. Known gaps — the database would not catch a missed check

| # | Finding | Where |
|---|---|---|
| **B1** | **FIXED, Phase 2 (`20260816150000`).** `two_factor_status_v` is a **view**, so the enable-and-force loop (which reads `pg_tables`) never saw it — and `GRANT … ON ALL TABLES` **does** include views. Without `security_invoker` it ran as its owner and bypassed `two_factor_enrollment_owner` entirely. **Measured before and after, from the real `app_backend` connection**: a caller bound to a user owning nothing read **7 of 7** accounts through the view while the table itself correctly returned **0**; after the fix, **0**, and a real owner still sees exactly their own row. The generalised guard is `tests/integration/test_rls_coverage.py`, and it was verified to fail by reverting the option before being trusted. | view at `20260801120000:236`; loop at `20260801120100:126-137`; grant at `20260801120100:36` |
| **B2** | **FIXED, Phase 2 (`20260816160000`).** Grants were table-wide, so Row-Level Security gave no column protection anywhere. Measured from `pg_attribute.attacl`: **zero columns in the whole schema carried their own grant**. ⚠️ `information_schema.column_privileges` reported **622** rows for `app_backend` and looks like the opposite answer — it expands a TABLE grant into one row per column and cannot distinguish the two. Now four columns carry their own ACL. | `20260816160000` |
| **B3** | **FIXED, Phase 2 (`20260816160000`).** `app_user_self_update` permitted self-writes to `role`, `email_verified_at`, `status` and `password_hash` — the policy says only that the row must be yours, never which parts of it you may change. `UPDATE` on `app_user` is now granted on **`full_name` only**. Measured before: all four ALLOWED; after: `permission denied for column …`. | `20260816160000` |
| **B4** | **FIXED, Phase 2 (`20260816160000`).** `class_level` — the parental-consent gate input — was student-writable. ⚠️ **It looked already-mitigated and was not**: `SET class_level = 11` alone returns a CHECK violation on `ck_group_matches_class`, because `science` is not a Class 11 group. The constraint rejects an inconsistent PAIR, never the escalation — setting `class_level` and `student_group` together succeeded and moved a Class 9 student out of the gate. **Data validation is not authorization.** `UPDATE` on `student_profile` is now `language_pref` only. | `20260816160000` |
| **B5** | **FIXED, Phase 2 (`20260816170000`).** `subscription_owner` was `FOR ALL`, so a user could set their own `status = 'active'` with a `current_period_end` satisfying `ck_subscription_active_has_period` — the revenue model. Split into `FOR SELECT` + `FOR INSERT`, and **`INSERT` narrowed to `(user_id, plan_code)`**, so `status` and `current_period_end` cannot be supplied at all and take their defaults. `service.py:173` supplies exactly those two columns and is unaffected. | `20260816170000` |
| **B6** | **FIXED, Phase 2 (`20260816170000`).** `auth_token_owner` was `FOR ALL`, so revocation was **reversible** — logout, password reset and the response to detected theft were all undoable by the owner. Replaced with `FOR SELECT` plus `FOR UPDATE … WITH CHECK (revoked = true)`: a **one-way door**. ⚠️ A column grant would NOT have worked — `GRANT UPDATE (revoked)` permits `false` as readily as `true`. Only a `WITH CHECK` expresses "this transition and not its inverse", which is the opposite conclusion from B2/B3. | `20260816170000` |
| **B7** | **FIXED, Phase 2 (`20260816170000`).** `attempt_student_own`, `attempt_answer_owner`, `mastery_owner`, `coverage_owner` and `readiness_owner` were `FOR ALL` — exactly the numbers `coverage_viewers_read`, `readiness_viewers_read`, `mastery_guardian_read` and `attempt_teacher_read` show a parent or teacher, so a student could rewrite the evidence about themselves. All five are now `FOR SELECT` on the owner, with **no write policy and no write grant**: nothing writes them yet, and the phase that builds those endpoints adds a narrow one. | `20260816170000` |
| **B8** | `quiz_teacher_write` checks only `created_by`. It never checks the space, and never checks the role — any user who created a quiz row owns it. | `20260801120100:342` |
| **B9** | **FIXED, classroom Phase 1 (`20261004120000`, `20261004120100`) — applied 2026-10-04 and re-verified on the live database.** `enrollment_student_join` self-enrolled into **any** space and `enrollment_leave` had no `WITH CHECK`. Both dropped; `app_backend` holds **no** write grant on `enrollment`; the only writers are `app.join_space_by_code` (live code, matching board/class/group, guardian gate, removed ≠ rejoinable), `app.leave_space` and `app.remove_student`. **Measured on a shadow database**: the same raw `INSERT INTO enrollment` as `app_backend` succeeds before and is `permission denied` after. | `20261004120000` §4 |
| **B10** | **FIXED, classroom Phase 1 (`20261004120000`) — applied 2026-10-04 and re-verified on the live database.** `classroom_space` had no role check — any user could create a space with `owner_role = 'teacher'`. `space_owner_write` (FOR ALL) replaced by `space_owner_update`; INSERT/UPDATE/DELETE revoked, `UPDATE (title, status)` granted back; creation only through `app.create_space`, which reads the role from the bound session. Plus `ck_space_owner_is_teacher`. Measured the same way as B9: a student's raw `INSERT INTO classroom_space` succeeds before, `permission denied` after. | `20261004120000` §2 |
| **B11** | **FIXED, classroom Phase 1 (`20261004120000`) — applied 2026-10-04 and re-verified on the live database.** `app.owns_space()` had **no subject-scope check**, so `teacher_subject_scope` governed only two policies. It now requires an active teacher **and** an unrevoked scope row for the space's subject; `app.teaches_student_subject` honours `revoked_at` too. Scope is self-declared by `app.create_space` (owner decision 2026-10-03) and withdrawn by an administrator stamping `revoked_at`. ⚠️ The quiz attempt teacher reads (`20260801120100:362`, `:384`) narrow with it — intended (`prd.md` §4.2 "own subject only"), and no route reaches them yet. | `20261004120000` §0–§1 |
| **B12** | `quiz_question` has a SELECT policy only, so the quiz-authoring path has **no write path** through `app_backend`. | `20260801120100:347` |
| **B13** | Six curriculum policies were changed to `USING (true)`, dropping the bound-user requirement they were created with. Curriculum data is now readable with no session at all. | `20260802140000:55-71` vs `20260801120100:238` |
| **B14** | `20260802140000`'s header states the six curriculum tables "were never given" a policy. Only the **read** half was missing — `20260801120100:232-247` already gave all six a `*_admin_write`. A migration comment that misdescribes the state it is fixing is how the next contributor inherits the wrong mental model. | `20260802140000:5-14` vs `20260801120100:232-247` |
| **B15** | `reqlog_insert` is `WITH CHECK (true)` — the operational log the admin panel reads is **forgeable** by anything holding the `app_backend` connection. | `20260801120100:488` |
| **B16** | `admin_profile_self` omits `user_id` from its `WITH CHECK`: `USING (user_id = cuid() OR app.is_admin())` but `WITH CHECK (app.is_admin())`, so any administrator may write **any** administrator's profile row. | `20260801120100:183` |
| **B17** | `oauth_identity_owner` is `FOR ALL` on a table with **no writer yet** — a user can pre-claim a victim's future social identity by inserting `(provider, provider_user_id)` before the feature ships. `uq_oauth_provider_subject` then makes the real link impossible. | `20260802120000:172`, table at `:96` |
| **B18** | `quiz_question_read` is safe only by accident: `EXISTS (SELECT 1 FROM public.quiz q WHERE q.id = quiz_id)` is gated purely by `quiz_read` applying to the inner query. Change `quiz_read` and this silently widens. | `20260801120100:347` |
| **B19** | **CLOSED STRUCTURALLY, Phase 2.** Grants are forward-looking via `ALTER DEFAULT PRIVILEGES` while enablement was a one-shot loop, so a new table is granted automatically and protected only if someone remembers — missed three times already (both default partitions, finding **F1**; and `two_factor_status_v`, which the loop could not see because it reads `pg_tables` and a view is not a table, finding **B1**). **The fix is a test, not a migration**: `tests/integration/test_rls_coverage.py` asserts every table in `public` has RLS enabled, forced, and a policy or a listed exemption, and every view runs as its caller. Both exemption lists are checked in both directions. ⚠️ Verified to FAIL before being trusted, by reverting `security_invoker` and confirming it named the object. | `tests/integration/test_rls_coverage.py` |

### B20–B26 — seven more `FOR ALL` policies, found 2026-08-16 during Phase 2

Phase 2 began by dumping the live catalogue rather than reading the migration files. §2.3 of the
plan named **7** tables whose `FOR ALL` policies needed splitting; the database has **31** such
policies. Ten are curriculum `*_admin_write` (predicate `app.is_admin()`, arguably correct), five
are named elsewhere in the register, and **nine were recorded nowhere**.

Each of the nine was put to the repository owner individually. **Two are now documented decisions**
rather than findings, and **seven are open**:

| # | Table · policy | Predicate | What the owner may therefore do |
|---|---|---|---|
| **B20** | `two_factor_enrollment` · `two_factor_enrollment_owner` | `user_id = app.current_user_id()` | **Clear their own `locked_until`, zero `failed_attempts`, change `method` or `status`** — the brute-force ladder this table exists to enforce is self-clearable at the database layer |
| **B21** | `two_factor_backup_code` · `two_factor_backup_code_owner` | `user_id = app.current_user_id()` | **Insert their own code hashes, or clear `used_at` on a spent code.** Backup codes are an authentication bypass by design, so this is the severity of a self-writable password |
| **B22** | `chat_session` · `chat_session_owner` | `student_id = app.current_user_id()` | Create, edit and delete their own tutoring sessions |
| **B23** | `visual_aid` · `visual_aid_owner` | via the owning session | Write generated-diagram rows into their own session |
| **B24** | `review_schedule` · `review_owner` | `student_id = app.current_user_id()` | Rewrite their own spaced-repetition schedule |
| **B25** | `parent_profile` · `parent_profile_self` | `user_id = app.current_user_id() OR app.is_admin()` | Rewrite their own profile row — the same shape as `student_profile_write` (**B4**) |
| **B26** | `teacher_profile` · `teacher_profile_self` | `user_id = app.current_user_id() OR app.is_admin()` | Same |

**None is reachable through any route today** — every write goes through narrow service code. They
are the second layer, and the point of a second layer is that it holds when the first has a bug.

⚠️ **B20 and B21 are the load-bearing pair.** They govern authentication itself, and the application
writes both **exclusively** through `SECURITY DEFINER` functions — so `FOR SELECT` on the owner
with no direct write path would cost nothing and close them outright.

⚠️ **B25 and B26 leave the three profile tables governed by different reasoning** once §2.2 narrows
`student_profile`. That inconsistency is deliberate and recorded, not an oversight.

#### Two decisions, not findings

**`message.message_owner` stays `FOR ALL`.** A student owns their own transcript outright. The
consequence, written down rather than left implicit: **the integrity of assistant turns is not a
database-level guarantee** — a student with arbitrary SQL as `app_backend` could insert a row into
their own session attributed to the assistant. Card 1.5's privacy invariant concerns who may *read*
chat content, and that still holds: `chat_session`, `message` and `visual_aid` remain owner-only
with no teacher, parent or admin path and no privileged function touching them.

~~**`join_code.join_code_owner` stays `FOR ALL`.**~~ **REVERSED by the repository owner on
2026-10-03, implemented in `20261004120000` §3.** The original reasoning: a space owner minting and
editing codes for a space they already own is the behaviour the feature exists to provide, and
`app.owns_space(...)` scopes it. Why it was reversed: while the owner could `INSERT` any string,
**code entropy and "one live code per space" were application promises, not database facts** — a
client bug or a future endpoint could store `AAAAAAAA`, and any student with a matching class could
then walk into a classroom of minors uninvited. Now `join_code_owner_read` is SELECT-only, codes
are minted in Python with `secrets`, written only by `app.rotate_join_code`, and held to
`ck_join_code_format` and `uq_join_code_one_live`.

### B27 — found while planning the classroom, 2026-10-03

| # | Finding | Where |
|---|---|---|
| **B27** | **FIXED, classroom Phase 3 (`20261004130000`) — applied 2026-10-04 and re-verified on the live database.** `announcement_write` was `FOR INSERT WITH CHECK (app.owns_space(space_id))` and never checked `author_id`, so a classroom owner could publish an announcement **attributed to any user** — another teacher, or a student in the class. Replaced by `announcement_insert`, `announcement_update` and `announcement_delete`, each requiring `author_id = app.current_user_id() AND app.owns_active_space(space_id)`; `UPDATE` narrowed to `(body, publish_at)` so `author_id` cannot be rewritten afterwards. **Measured on a shadow database**: an owner's raw `INSERT … author_id = <another teacher>` as `app_backend` succeeds on the 27-migration schema and is refused with `new row violates row-level security policy` after. `test_classroom_rls.py` `TestAnnouncementBoundary` pins it. | `20260801120100:302` → `20261004130000:76-90` |


### Related findings recorded elsewhere

Two more findings are database-adjacent and belong in the reader's mind here, though they are
catalogued in full in [`architecture.md`](architecture.md):

* **C1** — roughly ten `SECURITY DEFINER` functions accept a user identifier without checking it
  belongs to the caller. The sharpest is `app.insert_auth_token`
  (`20260802140000:182`), which will mint a token of **any kind, for any user, with a
  caller-chosen hash** — a complete authentication bypass for anyone who can reach it with
  controlled arguments. **Verified: no current route passes a request-controlled identifier.**
* **C2** — **FIXED, Phase 2 (`20260816180000`)** — `app.confirm_guardian_link` now requires `p_parent = app.current_user_id()`, and `app.reinvite_guardian_link` requires `p_student = app.current_user_id()`. ⚠️ **The two have different callers** — the parent confirms, the STUDENT invites — so a single shared check would have been wrong in one direction. Verified by reading both call sites and both service signatures
  (`20260802150000:75`).
* **C5** — five `SECURITY DEFINER` helper functions retain PostgreSQL's default `EXECUTE` grant to
  `PUBLIC`: `is_admin`, `is_verified_guardian_of`, `teaches_student_subject`, `owns_space`,
  `is_enrolled_in`. Every other privileged function is explicitly revoked
  (30 `REVOKE ALL ON FUNCTION` statements, 30 matching `GRANT EXECUTE`).

### Verified correct — recorded so nobody re-audits

* No SQL string interpolation anywhere; every query uses bound parameters.
* All `SECURITY DEFINER` functions carry `SET search_path`.
* `app.is_verified_guardian_of` and `app.teaches_student_subject` cannot be abused through their
  parameters.
* Card 1.5's chat-privacy invariant holds — `chat_session`, `message` and `visual_aid` are
  owner-only with no teacher, parent or admin path, and no privileged function touches them.
* `question_key` is genuinely unreachable from `app_backend`.
* The boot-time role guard (`backend/app/core/db.py:119-164`) makes "connected as `postgres`" a
  refusal to start rather than a silent, total loss of the policy layer.

---

## Migration rules

### Filename format

```
YYYYMMDDHHMMSS_snake_case_description.sql
```

Fourteen digits, an underscore, a description. Migrations run in **filename order**, which is why
the timestamp prefix is not decoration: `20260802140000` must be applied after `20260802120000`
because it forces RLS on tables the earlier file creates (`20260802140000:20-23`).

Create one with:

```bash
supabase migration new add_something_useful
```

### Never edit an applied migration

Add a new one. `20260803090000` is the canonical illustration: it corrects two policies from
`20260801120100` and says so in its header — *"That file is applied and is deliberately NOT edited
here; read `pg_policies`, not the file, for what is live"* (`20260803090000:42-44`).

This has a consequence worth internalising: **the migration files and the applied database can
diverge, and have.** `20260803090000:12-22` records a case where the applied
`guardian_link_update` policy was parent-only while the file said either participant, and a live
code path failed silently as a result. When in doubt, probe `pg_policies`.

### Make every migration re-runnable

The Supabase command-line interface **does not wrap a migration file in a transaction**. A failure
part-way through leaves the earlier statements committed and the migration unrecorded — and the
obvious retry then dies on "policy already exists". The first version of `20260802140000` hit
exactly that (`20260802140000:25-35`).

So: `CREATE OR REPLACE` for functions, `DROP POLICY IF EXISTS` before `CREATE POLICY` (PostgreSQL
has no `CREATE POLICY IF NOT EXISTS`), `ALTER … ENABLE/FORCE`, `IF NOT EXISTS`, and `ON CONFLICT DO
NOTHING` for seeds.

### A changed `RETURNS TABLE` needs drop-then-create

`RETURNS TABLE` columns are `OUT` parameters, so adding one **changes the function's return type**,
and PostgreSQL refuses outright: *"cannot change return type of existing function"* (SQLSTATE
42P13). `20260803160000:94-104` hit this adding `token_revoked` to `app.check_token_status`.

**Adding a parameter is the more dangerous case, because it fails quietly.** `CREATE OR REPLACE`
does not replace a function with a different arity — it **overloads** it. `20260803160000:70-76`
spells it out: without the explicit `DROP FUNCTION IF EXISTS app.activate_2fa(uuid);` both
`activate_2fa(uuid)` and `activate_2fa(uuid, bigint DEFAULT NULL)` would exist, and a
one-argument call would match both and fail at runtime with *"function name is not unique"*. The
drop is what makes it a replacement rather than an ambush.

### A drop takes its grant and its comment with it

`DROP FUNCTION` removes the function's `GRANT EXECUTE` and its `COMMENT ON FUNCTION` along with it.
Nothing warns you. Whenever a migration drops and recreates a function it must **re-issue**:

```sql
REVOKE ALL   ON FUNCTION app.thing(args) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.thing(args) TO   app_backend;
COMMENT ON FUNCTION app.thing(args) IS '…';
```

`20260803160000:158-179` does exactly this for all three functions it replaces. Forget it and the
function survives with the default `EXECUTE` to `PUBLIC` and no documentation — the silent version
of finding C5.

### A new type value cannot be used in the same transaction

PostgreSQL will not let a value added by `ALTER TYPE … ADD VALUE` be *used* in the same
transaction, and the Supabase CLI runs each migration as one. So the value gets its own file:
`20260802140100_token_kind_enrollment.sql` adds `two_factor_enrollment` to `token_kind` and does
nothing else. The code that writes it ships afterwards.

### A new table needs four things, not one

Because grants are forward-looking and RLS enablement is not (finding B19), a new table in `public`
must explicitly:

1. `ALTER TABLE … ENABLE ROW LEVEL SECURITY;`
2. `ALTER TABLE … FORCE ROW LEVEL SECURITY;`
3. carry at least one policy — or be deliberately policy-less, with a comment saying why, as
   `question_key` is;
4. and, if it is partitioned, repeat steps 1 and 2 on **every partition including the default**.

`20260802120000:134-139` does 1 and 2 for the three subscription tables — except that it omitted
`FORCE`, which `20260802140000:83-85` then had to add.

### Applying migrations

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

Per the project's engineering rules, **the agent never pushes a migration.** It produces the file,
verifies it with a dry run against a shadow or branch database, and reports the actual output; the
repository owner applies it.

### One manual step the migrations cannot do

`app_backend` is created `NOLOGIN` with no password, because passwords are never committed. Set it
once, out of band:

```sql
ALTER ROLE app_backend WITH LOGIN PASSWORD '<strong-password>';
```

Then point `DATABASE_URL` in `backend/.env` at **that role, not `postgres`**. Connecting as
`postgres` bypasses RLS and makes every policy on this page inert — which is why
`backend/app/core/db.py:119-164` refuses to start when it detects it.

---

## Connecting from FastAPI — the correct, synchronous pattern

The codebase is **entirely synchronous SQLAlchemy**: `Session`, `db.execute`, `sessionmaker`. There
is no `AsyncEngine`, no `async with engine.begin()`, and no `await` on a database call anywhere.

```python
from sqlalchemy import text
from sqlalchemy.orm import Session


def set_current_user_id(session: Session, user_id: UUID | str) -> None:
    parsed = UUID(str(user_id))
    session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(parsed)},
    )
```

`set_config(..., is_local => true)` is the parameterised equivalent of `SET LOCAL`, which cannot
take a bind parameter and would otherwise have to be built by string concatenation. Use this form;
it is the one every other module copies. Verbatim at `backend/app/core/db.py:33-59`.

Authenticated routes get the binding from `backend/app/auth/dependencies.py` (`authenticated`),
which binds the user from the verified token before yielding the session. `get_db`
(`backend/app/core/db.py:62-83`) yields a session with **no** user bound — the correct default for
an unauthenticated endpoint, and the reason registration binds the identifier it is about to create
before inserting the profile row.

---

## Keeping this page current

Per the update mandate in `/CLAUDE.md`: any change that adds, removes, renames or moves a table,
column, policy, privileged function, grant or migration **must update this page in the same
change** and append a line to [`/Claude/HISTORY.md`](../../Claude/HISTORY.md). The code-area to
document lookup is [`/Claude/DOC-SYNC-MAP.md`](../../Claude/DOC-SYNC-MAP.md);
`supabase/migrations/*` maps here.

Re-run every command in [At a glance](#at-a-glance--every-count-with-the-command-that-produced-it)
and update the numbers. A count without its command is not a measurement.
