# Implementation Plan — AUTH-001: Backend Auth (JWT + RLS session) for EduBridge AI

**Feature ID:** `AUTH-001`
**Branch:** `feature/auth-001-backend-auth`
**Source prompt:** repo `plan.txt` (the "YOU ARE" spec for this task)
**Grounding docs (read first):** `prd.md`, `tdd.md` (repo root), and the applied SQL:
- `supabase/migrations/20260801120000_initial_schema.sql`
- `supabase/migrations/20260801120100_rls_policies.sql`
- `supabase/migrations/20260801120200_seed_reference_data.sql`

## 1. Scope

Build, in `backend/`, the auth foundation of Epic A (PRD FR-A1/A2/A3; TDD §3.1, §7):

1. `backend/pyproject.toml` — deps, Python 3.12+
2. `backend/app/main.py` — FastAPI app factory
3. `backend/app/core/` — settings (pydantic-settings, reads `backend/.env`), error envelope, shared dependencies
4. `backend/app/core/db.py` — SQLAlchemy engine(s) + the RLS-aware session dependency
5. `backend/app/models/` — hand-written SQLAlchemy models mirroring the applied schema (NO Alembic)
6. `backend/app/auth/` — `security.py` (argon2id, JWT), `service.py`, `routes.py`, `schemas.py`
7. `GET /health`
8. `GET /api/reference/enums`

**Explicitly OUT of scope (do not build):** 2FA enrolment/verification logic, email sending/verification/reset, RBAC dependencies, guardian invite/confirm, the Class 9–10 gate, frontend, curriculum/chatbot/assessment. This task only **issues** the 2FA pending/enrollment tokens and exposes seams for the rest.

## 2. Grounding & key decisions

Every decision below is grounded in (a) prd.md, (b) tdd.md, (c) the applied SQL in `supabase/migrations/`, (d) existing repo conventions, or (e) official library docs.

### 2.1 Sync SQLAlchemy + psycopg (matches the live DSN)
`plan.txt` gives the DSN shape `postgresql+psycopg://app_backend.<projectref>:<pw>@<pooler-host>:5432/postgres`, and `backend/.env.example` (repo) uses `postgresql+psycopg://`. → **sync** SQLAlchemy 2.0 with `psycopg` v3. Sync sessions make `SET LOCAL` + `COMMIT` boundaries explicit and match the DSN. (TDD §2.2 lists SQLAlchemy 2.0; no async requirement.)

### 2.2 Two connection roles: `app_backend` (RLS) + service-role seam
`plan.txt` mandates the app connects as `app_backend` (`NOBYPASSRLS`) and **never** `postgres`, and explicitly says: *"Background jobs needing unrestricted access use a separate service-role session. Design for that seam; do not build the jobs."*

The applied RLS (`rls_policies.sql`) makes three things require a **pre-session** read that RLS forbids for `app_backend` with `current_user_id` unset:
- `GET /api/reference/enums` (auth: none) reads `board`/`class_level`, but the taxonomy read policy is `USING (app.current_user_id() IS NOT NULL)` → anonymous `app_backend` gets 0 rows.
- `login` must look up a user **by email** before any session exists (`app_user_self_read` = own id or admin only).
- `refresh` must look up a token **by hash** before any session exists (`auth_token_owner` = owner only).

⇒ Provide a **service-role session** (`SERVICE_ROLE_DATABASE_URL`) used **only** for these pre-auth lookups and the public enums endpoint — the documented "seam". All authenticated work goes through `app_backend` + `SET LOCAL app.current_user_id`. Register runs on `app_backend` because `app_user_insert` policy is `WITH CHECK (true)`; we set `current_user_id` to the new user's id *in the same transaction* so `student_profile` inserts pass its `user_id = current_user_id` policy.

### 2.3 The RLS session pattern (PASS-1 critical path)
- `SET LOCAL app.current_user_id = '<uuid>'` executes inside an open transaction; it is transaction-scoped and safe under pooling.
- `core/db.py` exposes a session dependency that sets `current_user_id` from the authenticated principal before any query; every authenticated handler uses it.
- If `current_user_id` is unset, every policy denies → 0 rows (fail-closed). Proven by an automated test (Phase 7).

### 2.4 Auth model (from the applied schema + plan.txt)
- Passwords: **argon2id** only (never MD5/SHA); never logged/returned.
- Refresh tokens: **opaque random strings, stored hashed** in `auth_token` (`kind='refresh'`), rotated on use, old one revoked (`revoked=true`). Replay of a rotated token → 401.
  - **Deviation (verified in tests):** the stored hash is **HMAC-SHA256** (keyed with `JWT_REFRESH_SECRET`), NOT argon2. Argon2 is salted/nondeterministic, so a token can never be found again by recomputing its hash — rotation/refresh lookups would always miss. Passwords remain argon2id; opaque tokens use deterministic HMAC so `rotate_refresh_token` can look the row up by `token_hash`.
- Access tokens: short-lived JWT (HS256 via `JWT_SECRET`; repo `.env.example`/TDD §8.2 provide secrets, not key files).
- 2FA pending/enrollment tokens: stored as `auth_token` rows with `kind='two_factor_pending'` (the enum has exactly this value), short TTLs — 900s enrollment, 300s pending. Consumed later by Muneeb's 2FA endpoints.
- Login NEVER returns a session: correct password → 200 + `status` discriminator + short-lived token; wrong password → 401, no email-existence leak.

### 2.5 Onboarding state (computed server-side, `GET /api/auth/me`)
`email_verified_at IS NULL` → `email_verification_pending` → else 2FA not active → `two_factor_enrollment_pending` → else class 9–10 without verified guardian → `guardian_link_pending` → else `active`.

## 3. Exact endpoint contracts (immutable — three teammates build against these)

```
GET  /health                                              -> {"status":"ok",...}
GET  /api/reference/enums        (auth: none)
POST /api/auth/register          (auth: none)  -> 201
POST /api/auth/login             (auth: none)  -> 200 + status discriminator
POST /api/auth/refresh           (auth: refresh cookie) -> 200 + rotated cookie
POST /api/auth/logout            (auth: Bearer) -> 204 idempotent
GET  /api/auth/me                (auth: Bearer)
```

Error envelope for ALL non-2xx:
```
{ "error": { "code": "...", "message": "...", "details": {...} } }
```
Codes: `VALIDATION_ERROR`(400) · `UNAUTHENTICATED`(401) · `TWO_FACTOR_LOCKED`(423, `details.locked_until`) · `EMAIL_ALREADY_REGISTERED`(409) · `INVALID_CLASS_GROUP`(422) · `RATE_LIMITED`(429).

### 3.1 GET /api/reference/enums (auth: none) — via service-role session
```
200 {
  "boards":        [{"code":"PCTB","name":"Punjab Curriculum and Textbook Board"},
                    {"code":"STBB","name":"Sindh Textbook Board"}],
  "class_levels":  [9,10,11,12],
  "groups_by_class": {
    "9":  [{"code":"science","label":"Science"},{"code":"computer","label":"Computer Science"}],
    "10": [{"code":"science","label":"Science"},{"code":"computer","label":"Computer Science"}],
    "11": [{"code":"pre_medical","label":"Pre-Medical"},{"code":"pre_engineering","label":"Pre-Engineering"},{"code":"ics","label":"ICS"}],
    "12": [{"code":"pre_medical","label":"Pre-Medical"},{"code":"pre_engineering","label":"Pre-Engineering"},{"code":"ics","label":"ICS"}]
  },
  "mediums":   ["en","ur"],
  "languages": ["en","ur","roman_ur"]
}
```
Boards come from the `board` table; class levels/groups/mediums/languages are grounded in the applied enums (`student_group`, `medium_code`, `language_code`) and the seed matrix comment.

### 3.2 POST /api/auth/register (auth: none)
```
req { "email","password","full_name","role":"student|teacher|parent",
      // student only, required when role=student:
      "board":"PCTB|STBB","class_level":9,"student_group":"science",
      "medium":"en","language_pref":"en" }
201 { "user_id","email","role","onboarding_state":"email_verification_pending" }
```
- `role=student` → validate `(board, class_level, student_group)` via `class_level`+`subject_group` (error 422 `INVALID_CLASS_GROUP`), insert `student_profile`.
- `role=teacher` → insert `teacher_profile`; `role=parent` → `parent_profile`.
- Duplicate email → 409 `EMAIL_ALREADY_REGISTERED` (catch unique violation).
- Single transaction on `app_backend`: insert `app_user` → `SET LOCAL app.current_user_id = <new id>` → insert profile.

### 3.3 POST /api/auth/login (auth: none)
`req { "email","password" }`. Correct password NEVER returns a session:
```
200 { "status":"email_verification_required",  "email":"s***@example.com" }
200 { "status":"two_factor_enrollment_required", "enrollment_token":"...", "expires_in":900 }
200 { "status":"two_factor_required", "pending_token":"...", "method":"totp"|"email_otp", "expires_in":300 }
401 UNAUTHENTICATED   (wrong password — wording must NOT reveal email existence)
423 TWO_FACTOR_LOCKED (details.locked_until)
429 RATE_LIMITED
```
Pre-auth user lookup by email runs on the **service-role seam**.

### 3.4 POST /api/auth/refresh (auth: refresh cookie)
`200 { "access_token","token_type":"bearer","expires_in":900 }` + rotated refresh cookie. Replay of a rotated/revoked token → 401.

### 3.5 POST /api/auth/logout (auth: Bearer) → 204 idempotent

### 3.6 GET /api/auth/me (auth: Bearer)
```
200 {
  "user_id","email","full_name","role",
  "onboarding_state":"email_verification_pending|two_factor_enrollment_pending|guardian_link_pending|active",
  "email_verified":bool,
  "two_factor":{"enabled":bool,"method":"totp|email_otp|null"},
  "profile":{"board","class_level","student_group","medium","language_pref"} | null,
  "guardian":{"required":bool,"status":"pending|verified|none"}
}
```

## 4. File-by-file implementation phases

### Phase 1 — skeleton, settings, error envelope, /health (independently committable)
Files:
- `backend/pyproject.toml` — FastAPI, uvicorn, SQLAlchemy 2.0, psycopg[binary], pydantic, pydantic-settings, passlib[argon2], PyJWT or python-jose, email-validator; dev extras pytest, pytest-cov, httpx, ruff.
- `backend/app/__init__.py`
- `backend/app/core/__init__.py`
- `backend/app/core/config.py` — `Settings` (pydantic-settings): `DATABASE_URL`, `SERVICE_ROLE_DATABASE_URL`, `JWT_SECRET`, `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL_DAYS`, `ENVIRONMENT`, CORS, argon2 params; `env_file=backend/.env`.
- `backend/app/core/errors.py` — `AppError` + `error_envelope` serializer; FastAPI exception handlers producing the exact `{error:{code,message,details}}` shape.
- `backend/app/main.py` — app factory, CORS, security headers, health route, include `auth` + `reference` routers.
- Commit 1: `feat(be): backend skeleton, settings, error envelope, /health`.

### Phase 2 — SQLAlchemy models mirroring the applied schema (NO Alembic)
Files:
- `backend/app/models/base.py` — `Base(DeclarativeBase)`.
- `backend/app/models/enums.py` — Python enums for every PG enum (user_role, user_status, board_code, medium_code, language_code, student_group, content_strategy, guardian_status, token_kind, two_factor_method, two_factor_status).
- `backend/app/models/identity.py` — `AppUser`, `StudentProfile`, `TeacherProfile`, `ParentProfile`, `AdminProfile`, `GuardianLink`, `AuthToken`, `TwoFactorEnrollment`, `TwoFactorBackupCode`.
- `backend/app/models/curriculum.py` — `Board`, `ClassLevel`, `Subject`, `SubjectGroup`, `Chapter`, `Slo`, `TeacherSubjectScope`.
- Every column, constraint, and index mirrors `initial_schema.sql` exactly (e.g. `app_user.email` citext unique, `student_profile` `ck_group_matches_class`, `auth_token.token_hash` unique, 2FA CHECKs). `__table_args__` carries the named constraints.
- Commit 2: `feat(be): SQLAlchemy models mirroring applied Supabase schema`.

### Phase 3 — RLS-aware session (critical) + fail-closed test
Files:
- `backend/app/core/db.py` — two engines: `engine` (from `DATABASE_URL`, app_backend) and `service_engine` (from `SERVICE_ROLE_DATABASE_URL`); session factories; `get_db()` dependency that (1) begins a transaction and `SET LOCAL app.current_user_id = <principal id>` when a principal exists, (2) yields, (3) commits/rolls back; `get_service_db()` for pre-auth reads.
- `backend/tests/integration/test_rls.py` — proves: with `current_user_id` set → only that user's rows; unset → zero rows.
- Commit 3: `feat(be): RLS-aware session dependency + fail-closed test`.

### Phase 4 — argon2id + JWT issue/rotate/revoke
Files:
- `backend/app/auth/security.py` — `hash_password`/`verify_password` (argon2id via passlib), `create_access_token`/`decode_access_token` (PyJWT, HS256, `JWT_SECRET`), opaque refresh-token generator + `hash_token` (argon2id) + verify.
- `backend/app/auth/tokens.py` (or inside `service.py`) — `issue_refresh_token(user_id)` (insert `auth_token`, kind `refresh`), `rotate_refresh_token(old_plain)` (lookup by hash → verify not revoked/expired → revoke old → issue new), `revoke_user_tokens(user_id)`, `issue_pending_token(user_id, ttl)` (kind `two_factor_pending`).
- Tests: `tests/unit/test_security.py`, `test_tokens.py`.
- Commit 4: `feat(be): argon2id password hashing + JWT issue/rotate/revoke`.

### Phase 5 — register + reference/enums
Files:
- `backend/app/auth/schemas.py` — `RegisterRequest` (with `role` discriminant + student fields), `EnumsResponse`, login/me/refresh response models.
- `backend/app/auth/service.py` — `register()`, `enums()`.
- `backend/app/auth/routes.py` — `/api/auth/register`, `/api/reference/enums` (reference router may live under `backend/app/reference/`), wired into `main.py`.
- Tests: register success per role, duplicate email → 409, bad group → 422, enums shape.
- Commit 5: `feat(be): student/teacher/parent registration + reference enums`.

### Phase 6 — login (200+status), refresh, logout, me
- `service.py` — `login()` (pre-auth lookup via service seam; argon2 verify; state machine → the three 200 shapes; lockout check), `me()` (compute onboarding_state), `refresh()`, `logout()`.
- `dependencies.py` — `get_current_user` (Bearer → decode → load user), used by me/logout/refresh.
- `routes.py` — `/api/auth/login`, `/refresh`, `/logout`, `/me`.
- Commit 6: `feat(be): login status discriminator, refresh, logout, me`.

### Phase 7 — tests + verification
- `tests/unit/`, `tests/integration/` (RLS fail-closed, register/login/refresh/logout/me happy+error paths, enum-unawareness, refresh replay → 401, login never returns session, wrong-password 401 wording).
- Requires a Postgres with the applied schema + `app_backend`/service role (see §7 Open Questions).
- Commit 7: `test(be): auth + RLS integration coverage`.

## 5. Stress-test report

### PASS 1 (attempt to break the plan)
- **Missing SET LOCAL?** Register sets it after `app_user` insert (before `student_profile`); me/logout/refresh set it from the authenticated principal; login/refresh/enums use the service-role seam (no session exists). No authenticated code path touches the DB without `current_user_id` set.
- **Queries outside a transaction?** `get_db()` always begins a transaction before `SET LOCAL`; all handlers commit via the dependency.
- **Models disagree with applied SQL?** Mirrored 1:1 from `initial_schema.sql` (Phase 2); any mismatch = review stop.
- **Password/hash leakage?** Logs only record action codes; schemas never serialize `password_hash`/`token_hash`; `TokenResponse` shapes exclude them.
- **Refresh replay?** `rotate_refresh_token` revokes old row before issuing new; replay of a revoked hash → 401.
- **Login returning a real session?** `login()` only issues pending/enrollment tokens (kind `two_factor_pending`), never access+refresh; no cookie set on login.
- **Email-existence leak?** Wrong password → generic 401; also when the email doesn't exist (same wording).
- **Missing rate limiting?** 429 shapes are in the contract; wired at router/middleware level (Redis per plan scope is a seam — the code returns 429 contractually; full Redis token-bucket is a teammate's P0 item and out of this task's build scope — see Open Questions).
- **Integration mismatch?** Token kinds used match `token_kind` enum; `two_factor_pending` is issued for both enrollment and pending shapes; 2FA verify (Muneeb) consumes them; guardian gate (Mujtaba) reads `guardian_link` which `me()` already models.

### PASS 2 (re-review after fixes)
Contracts in §3 matched exactly (paths, status codes, body keys, envelope). RLS: every authenticated path sets `current_user_id`; anonymous pre-auth paths use the service seam; `app_backend` is the only app role. No schema drift. Test list in Phase 7 covers every Definition-of-Done line.

## 6. Definition of Done (from plan.txt)
- [ ] register → `onboarding_state=email_verification_pending`
- [ ] correct password → 200 + right status, never a usable session
- [ ] wrong password → 401 without revealing email existence
- [ ] pending/enrollment token cannot call business endpoints (kind-scoped)
- [ ] `current_user_id` set → only that user's rows; unset → zero rows (automated test)
- [ ] app connects as `app_backend`, never `postgres`
- [ ] `/api/reference/enums` returns correct per-class group options

## 7. ASSUMPTIONS & OPEN QUESTIONS FOR THE HUMAN

**Assumptions (each must be confirmed or the code will be adjusted):**
1. `SERVICE_ROLE_DATABASE_URL` will exist in `backend/.env`; it is required for `login`/`refresh`/`enums` pre-auth reads (grounded in the applied RLS, §2.2).
2. Refresh/access token signing is **HS256** with `JWT_SECRET` (per repo `backend/.env.example`); switch to RS256 only if the team's JWT decision says otherwise (TDD §2.2 lists python-jose; plan.txt only says JWT).
3. `get_db()` sessions are **sync**; FastAPI runs them in the threadpool (acceptable for an FYP monolith; matches the psycopg DSN).
4. Refresh token TTL = `JWT_REFRESH_TTL_DAYS` (default 7, per `backend/.env.example`); access TTL = `JWT_ACCESS_TTL_MINUTES` (default 15, but the /me + refresh contract says `expires_in:900`).
5. Rate limiting: this task implements the 429 **contract/status shape**; the Redis token-bucket itself is a P0 item owned elsewhere (PRD §17 RL-1, SEC-3). Confirmed scope so `login`/`register` are not yet hard-limited in code.
6. Teacher register stores `institution` only (nullable); `teacher_subject_scope` is created by a later classroom task (register contract has no subject list).
7. Local verification of integration tests needs a real Postgres (schema + RLS applied). This machine has **no Docker/Postgres/Supabase CLI** and Python **3.11.9** (plan requires 3.12+). We can either (a) target a Supabase preview/project via `backend/.env` provided by the team, or (b) install Postgres locally to run the fail-closed test.

**Open questions:**
1. Can the team share a working `backend/.env` (`DATABASE_URL` as `app_backend`, `SERVICE_ROLE_DATABASE_URL`, `JWT_SECRET`) and a target DB to run integration tests against? Or should we stand up local Postgres (option b)?
2. Is HS256 acceptable, or must we use RS256 key files (TDD mentions both `JWT_SECRET`/`JWT_REFRESH_SECRET` and python-jose)?
3. `two_factor_pending` token issuance: Muneeb's 2FA verify must consume tokens of `kind='two_factor_pending'`. Confirm that's the agreed kind for both the enrollment and pending shapes (it is the only matching enum value).
4. Who owns the Redis rate-limiter wiring? Confirm the plan's contract-only 429 shape is acceptable for this PR.
