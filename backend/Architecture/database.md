# Database

> The EduBridge AI schema as it is actually applied — tables, the complete Row-Level Security
> (RLS) policy catalogue, the `app.*` privileged functions, the invariants, and the known gaps.
>
> **Snapshot: 2026-08-15 · commit `eea0e74` · 11 applied migrations.**
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
| Applied migrations | **11** | `ls supabase/migrations/*.sql \| wc -l` |
| `CREATE TABLE` statements | **48** | `grep -hE '^CREATE TABLE' supabase/migrations/*.sql \| wc -l` |
| …of which DEFAULT partitions | **2** | `grep -hE '^CREATE TABLE.*PARTITION OF' supabase/migrations/*.sql \| wc -l` |
| Base tables (48 − 2) | **46** | derived from the two rows above |
| Views | **1** | `grep -hE '^CREATE VIEW' supabase/migrations/*.sql \| wc -l` |
| Enumerated types | **22** | `grep -hE '^CREATE TYPE' supabase/migrations/*.sql \| wc -l` |
| Indexes | **40** | `grep -hE '^CREATE INDEX' supabase/migrations/*.sql \| wc -l` |
| Triggers | **9** | `grep -hE '^CREATE TRIGGER' supabase/migrations/*.sql \| wc -l` |
| `CREATE POLICY` occurrences | **73** | `grep -o 'CREATE POLICY' supabase/migrations/*.sql \| wc -l` |
| …real `CREATE POLICY` statements | **72** | `grep -hE '^[[:space:]]*CREATE POLICY' supabase/migrations/*.sql \| wc -l` |
| **Live policy objects** | **73** | see [the reconciliation](#why-73-73-and-72-are-all-correct) |
| `CREATE OR REPLACE FUNCTION` statements | **37** | `grep -hE '^CREATE OR REPLACE FUNCTION' supabase/migrations/*.sql \| wc -l` |
| Distinct `app.*` function names ever defined | **34** | `grep -ohE 'CREATE OR REPLACE FUNCTION app\.[a-zA-Z0-9_]+' supabase/migrations/*.sql \| sed 's/.*app\.//' \| sort -u \| wc -l` |
| **Live `app.*` functions** (34 − 1 dropped) | **33** | `grep -nE 'DROP FUNCTION' supabase/migrations/*.sql` shows `issue_token_for_email` retired |
| `SECURITY DEFINER` function definitions | **35** | `grep -hE '^[^-]*SECURITY DEFINER' supabase/migrations/*.sql \| wc -l` |
| Definitions carrying `SET search_path` | **36** | `grep -hE '^SET search_path' supabase/migrations/*.sql \| wc -l` |
| `REVOKE ALL ON FUNCTION … FROM PUBLIC` | **30** | `grep -hE '^REVOKE ALL ON FUNCTION' supabase/migrations/*.sql \| wc -l` |
| `GRANT EXECUTE … TO app_backend` | **30** | `grep -hE '^GRANT EXECUTE' supabase/migrations/*.sql \| wc -l` |
| Implemented HTTP endpoints | **17 of 48** | `grep -cE '^@router\.' backend/app/auth/routes.py` (plus `/health` in `backend/app/main.py`) |

**36 of the 37 function definitions carry `SET search_path`.** The exception is
`app.set_updated_at()` (`20260801120000_initial_schema.sql:85`), a plain trigger function that is
not `SECURITY DEFINER` and therefore has nothing to escalate. Two definitions are not
`SECURITY DEFINER`: that trigger, and `app.current_user_id()`
(`20260801120100_rls_policies.sql:49`), which only reads a session setting.

### Why 73, 73 and 72 are all correct

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
| `app_user` | `20260801120000_initial_schema.sql:97` | `email citext UNIQUE`, `password_hash` (argon2id), `role user_role`, `status user_status`, `email_verified_at`, soft-delete `deleted_at`. Trigger `trg_app_user_updated` at `:109`. |
| `student_profile` | `:114` | `board`, `class_level` (9–12), `student_group`, `medium`, `language_pref`. `ck_group_matches_class` at `:124` forbids an FSc group on a Matric class and vice versa. |
| `teacher_profile` | `:133` | `institution` only. |
| `parent_profile` | `:140` | Timestamps only. |
| `admin_profile` | `:146` | Free-text `scope`. |

`class_level` on `student_profile` is the input to the parental-consent gate — see
[B4](#b-known-gaps--the-database-would-not-catch-a-missed-check).

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
| `two_factor_status_v` **(view)** | `:236` | Admin support view: method, status, lockout state and an unused-code count, with **no secret and no code hash**. |

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
| `teacher_subject_scope` | `:311` | Many-to-many least-privilege scope: which subjects a teacher may see. |

Seeded by `20260801120200_seed_reference_data.sql` — two boards, four class levels each, the
subject matrix documented at `:6-19`, and the group mappings at `:91-96`. Idempotent.

### Classroom and spaces

| Table | Defined at | Notes |
|---|---|---|
| `classroom_space` | `20260801120000_initial_schema.sql:324` | `owner_role space_owner_role` (teacher or parent). `ck_teacher_space_has_subject` (`:334`) forces a teacher space to declare its subject, because subject-scoping depends on it. |
| `join_code` | `:341` | Unique code, revocable, optional expiry. Never readable by students — they receive it out of band. |
| `enrollment` | `:351` | Joining a space **is** the consent record. `left_at` is the soft leave. |
| `announcement` | `:364` | Space-scoped, author-attributed. |

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

**All 73 live policy objects.** Every one is `TO app_backend`; no other role has a policy. An empty
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
| `classroom_space` | `space_owner_write` | ALL | `owner_id = cuid()` | `owner_id = cuid()` | `20260801120100:269` |
| `join_code` | `join_code_owner` | ALL | `app.owns_space(space_id) OR app.is_admin()` | `app.owns_space(space_id)` | `20260801120100:275` |
| `enrollment` | `enrollment_visible` | SELECT | `student_id = cuid() OR app.owns_space(space_id) OR app.is_admin()` | — | `20260801120100:281` |
| `enrollment` | `enrollment_student_join` | INSERT | — | `student_id = cuid()` | `20260801120100:289` |
| `enrollment` | `enrollment_leave` | UPDATE | `student_id = cuid() OR app.owns_space(space_id)` | *(none — falls back to `USING`)* | `20260801120100:294` |
| `announcement` | `announcement_read` | SELECT | `app.is_enrolled_in(space_id) OR app.owns_space(space_id) OR app.is_admin()` | — | `20260801120100:298` |
| `announcement` | `announcement_write` | INSERT | — | `app.owns_space(space_id)` | `20260801120100:302` |

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
| `two_factor_status_v` | **Not deliberate.** A view cannot carry RLS, and this one has no `security_invoker`. This is [B1](#b-known-gaps--the-database-would-not-catch-a-missed-check). |

---

## The `app.*` privileged functions

**33 live**, from 34 distinct names ever defined — `app.issue_token_for_email` was dropped as a
byte-for-byte duplicate of `app.insert_auth_token` (`20260803160000:151-153`).

All are in the `app` schema. All but two are `SECURITY DEFINER`; all but one carry
`SET search_path = public, pg_temp`, which is what prevents a shadowing attack from redirecting an
unqualified name inside the body. None takes dynamic SQL, and every query in the codebase uses
bound parameters.

### Row-Level Security helpers — called by policies, not by routes

These six are the ones the policy predicates above call. **Five of the six retain PostgreSQL's
default `EXECUTE` grant to `PUBLIC`** — there is no `REVOKE` for them anywhere in the migrations
(finding C5). They are `SECURITY DEFINER` so that reading the tables they check does not recurse
into the very policies calling them.

| Function | Volatility | Definer? | Returns | Grant | Defined at |
|---|---|---|---|---|---|
| `app.current_user_id()` | `STABLE` | **No** | `uuid` — the bound user, or `NULL` | default `PUBLIC` | `20260801120100:49` |
| `app.is_admin()` | `STABLE` | Yes | `boolean` — caller is an `active` `admin` | default `PUBLIC` | `20260801120100:56` |
| `app.is_verified_guardian_of(p_student uuid)` | `STABLE` | Yes | `boolean` — a **verified** link exists | default `PUBLIC` | `20260801120100:67` |
| `app.teaches_student_subject(p_student uuid, p_subject uuid)` | `STABLE` | Yes | `boolean` — active enrolment in a space the caller owns **and** a matching `teacher_subject_scope` row | default `PUBLIC` | `20260801120100:81` |
| `app.owns_space(p_space uuid)` | `STABLE` | Yes | `boolean` | default `PUBLIC` | `20260801120100:99` |
| `app.is_enrolled_in(p_space uuid)` | `STABLE` | Yes | `boolean` — enrolled and `left_at IS NULL` | default `PUBLIC` | `20260801120100:109` |

`app.is_verified_guardian_of` and `app.teaches_student_subject` were checked in the Epic 1 review
and **cannot be abused through their parameters** — both anchor on `app.current_user_id()`
internally, so passing an arbitrary student identifier proves nothing.

### The trigger function

| Function | Volatility | Definer? | Returns | Grant | Defined at |
|---|---|---|---|---|---|
| `app.set_updated_at()` | default `VOLATILE` | No | `trigger` — sets `NEW.updated_at = now()` | default `PUBLIC` | `20260801120000:85` |

Wired to nine tables (`grep -c '^CREATE TRIGGER' supabase/migrations/*.sql`). Three profile tables
carry `updated_at` columns with **no** trigger attached — finding D14.

### Session and token lifecycle — `POST /auth/login`, `/auth/refresh`, `/auth/logout`

| Function | Volatility | Definer? | Returns | Called from | Grant | Defined at |
|---|---|---|---|---|---|---|
| `app.lookup_user_for_login(p_email text)` | `STABLE` | Yes | `TABLE(id, password_hash, status, email_verified_at, role)` — deliberately not `SELECT *`. **`role` was added by `20260816140000`** so `login()` can decide which of the two sign-in endpoints an account may use (FR-A2a) inside the query it was already making, rather than as a second round trip on the hot login path | `backend/app/auth/service.py:305-313` (`login`, `:278`) → `POST /auth/login` (`routes.py:104`) and `POST /auth/admin/login` (`routes.py:115`) | `app_backend` | `20260816140000:57` (originally `20260802140000:115`) |
| `app.lookup_2fa_for_login(p_user_id uuid)` | `STABLE` | Yes | `TABLE(method, status, locked_until)` — no secret, no counter | `service.py:324` (`login`) → `POST /auth/login` | `app_backend` | `20260803180000:36` |
| `app.lookup_refresh_token(p_token_hash text)` | `STABLE` | Yes | `TABLE(id, user_id, kind, revoked, expires_at)`; takes a hash, never a plaintext token | `backend/app/auth/tokens.py:80` (`find_token`, `:76`) → `POST /auth/refresh` (`routes.py:109`) | `app_backend` | `20260802140000:133` |
| `app.insert_auth_token(p_user_id uuid, p_kind token_kind, p_token_hash text, p_expires_at timestamptz)` | `VOLATILE` | Yes | `uuid` | `tokens.py:54` (`_insert_token`, `:50`) — every token-issuing path | `app_backend` | `20260802140000:182` |
| `app.revoke_auth_token(p_id uuid)` | `VOLATILE` | Yes | `void` | `tokens.py:119` (`rotate_refresh_token`, `:98`) | `app_backend` | `20260802140000:152` |
| `app.revoke_refresh_family(p_user_id uuid)` | `VOLATILE` | Yes | `integer` — how many were revoked, so the caller can audit it | `tokens.py:134` (`revoke_refresh_family`, `:125`) — reuse-detection breach response | `app_backend` | `20260802140000:163` |

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

---

## Known gaps

Recorded here rather than deferred until fixed, per the Phase 0 honesty rules. These are findings
**B1–B19** of the 35-finding Epic 1 register.

### How to read this section

**These are defence-in-depth failures, not remote exploits.** Reaching any of them requires the
ability to run arbitrary SQL as `app_backend`, and every implemented route is narrow — 17 of 48
endpoints exist, each issuing fixed statements with bound parameters. The Epic 1 review confirmed
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
| **B1** | `two_factor_status_v` is a **view**, so the enable-and-force loop (which reads `pg_tables`) never saw it — and `GRANT … ON ALL TABLES` **does** include views. It has no `security_invoker`, so it runs as its owner and bypasses `two_factor_enrollment_owner` entirely. Exposes every account's two-factor method, lockout state and unused-backup-code count. | view at `20260801120000:236`; loop at `20260801120100:126-137`; grant at `20260801120100:36` |
| **B2** | **Grants are table-wide, so Row-Level Security gives no column protection on any table.** See invariant 4. | `20260801120100:36-39` |
| **B3** | `app_user_self_update` permits self-writes to `role`, `email_verified_at`, `status` and `password_hash` — the predicate constrains *which row*, never *which columns*. | `20260801120100:147` |
| **B4** | `student_profile_write` is `FOR ALL`, so `class_level` — the input to the parental-consent gate — is student-writable. | `20260801120100:168` |
| **B5** | `subscription_owner` is `FOR ALL`: a user can set their own `status = 'active'`. | `20260802120000:157` |
| **B6** | `auth_token_owner` is `FOR ALL`: revocation is reversible, so logout, password reset and the token-theft response are all undoable by their subject. | `20260801120100:209` |
| **B7** | `attempt_student_own`, `attempt_answer_owner`, `mastery_owner`, `coverage_owner` and `readiness_owner` are all `FOR ALL` — **every number a parent or teacher reads is student-writable**. | `:351`, `:367`, `:392`, `:401`, `:414` |
| **B8** | `quiz_teacher_write` checks only `created_by`. It never checks the space, and never checks the role — any user who created a quiz row owns it. | `20260801120100:342` |
| **B9** | `enrollment_student_join` self-enrols into **any** space; `enrollment_leave` has no `WITH CHECK`. | `:289`, `:294` |
| **B10** | `classroom_space` has no role check — any user can create a space with `owner_role = 'teacher'`. | `20260801120100:269` |
| **B11** | `teacher_subject_scope` governs only two policies (`coverage_viewers_read`, `readiness_viewers_read`, through `app.teaches_student_subject`). Every other teacher read goes through `app.owns_space()`, which has **no subject-scope check at all**. | `:406`, `:419` vs `:99` |
| **B12** | `quiz_question` has a SELECT policy only, so the quiz-authoring path has **no write path** through `app_backend`. | `20260801120100:347` |
| **B13** | Six curriculum policies were changed to `USING (true)`, dropping the bound-user requirement they were created with. Curriculum data is now readable with no session at all. | `20260802140000:55-71` vs `20260801120100:238` |
| **B14** | `20260802140000`'s header states the six curriculum tables "were never given" a policy. Only the **read** half was missing — `20260801120100:232-247` already gave all six a `*_admin_write`. A migration comment that misdescribes the state it is fixing is how the next contributor inherits the wrong mental model. | `20260802140000:5-14` vs `20260801120100:232-247` |
| **B15** | `reqlog_insert` is `WITH CHECK (true)` — the operational log the admin panel reads is **forgeable** by anything holding the `app_backend` connection. | `20260801120100:488` |
| **B16** | `admin_profile_self` omits `user_id` from its `WITH CHECK`: `USING (user_id = cuid() OR app.is_admin())` but `WITH CHECK (app.is_admin())`, so any administrator may write **any** administrator's profile row. | `20260801120100:183` |
| **B17** | `oauth_identity_owner` is `FOR ALL` on a table with **no writer yet** — a user can pre-claim a victim's future social identity by inserting `(provider, provider_user_id)` before the feature ships. `uq_oauth_provider_subject` then makes the real link impossible. | `20260802120000:172`, table at `:96` |
| **B18** | `quiz_question_read` is safe only by accident: `EXISTS (SELECT 1 FROM public.quiz q WHERE q.id = quiz_id)` is gated purely by `quiz_read` applying to the inner query. Change `quiz_read` and this silently widens. | `20260801120100:347` |
| **B19** | **Row-Level Security enablement is a one-shot loop while grants are forward-looking.** `ALTER DEFAULT PRIVILEGES` (`:38-41`) grants every *future* table automatically; the `ENABLE`/`FORCE` loop (`:126-137`) ran once. Every table added from now on is granted by default and protected only if someone remembers. | `20260801120100:36-41` vs `:126-137` |

### Related findings recorded elsewhere

Two more findings are database-adjacent and belong in the reader's mind here, though they are
catalogued in full in [`architecture.md`](architecture.md):

* **C1** — roughly ten `SECURITY DEFINER` functions accept a user identifier without checking it
  belongs to the caller. The sharpest is `app.insert_auth_token`
  (`20260802140000:182`), which will mint a token of **any kind, for any user, with a
  caller-chosen hash** — a complete authentication bypass for anyone who can reach it with
  controlled arguments. **Verified: no current route passes a request-controlled identifier.**
* **C2** — `app.confirm_guardian_link` does not check `p_parent = app.current_user_id()`
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
