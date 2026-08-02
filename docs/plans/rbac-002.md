# Implementation Plan — RBAC-002: Parental-consent gate + RBAC dependencies for EduBridge AI

**Feature ID:** `RBAC-002`
**Branch:** `feature/rbac-002-guardian-gate`
**Source prompt:** repo `plan.txt` (the "YOU ARE" spec for this task), versioned against `prd.md` + `tdd.md` **v0.3.4**.
**Grounding docs (read first):** `prd.md` (esp. §4.2 RBAC matrix, §4.3 parental gate), `tdd.md` (esp. §3.1 auth/guardian rows + derivation table, §6.8 RLS, §14.4 contract findings), and the applied SQL + existing code:
- `supabase/migrations/20260801120000_initial_schema.sql` (guardian_link L156–174, auth_token L176–187, audit/api_request_log partitions L627–660)
- `supabase/migrations/20260801120100_rls_policies.sql` (guardian_link policies L185–204, enable/force loop L121–137, app_user_insert L154–155, audit/reqlog policies L477–488, tss_read L246–248)
- `supabase/migrations/20260802140000_reference_read_and_auth_lookups.sql` (narrow SECURITY DEFINER pattern)
- `backend/app/auth/dependencies.py`, `backend/app/auth/service.py`, `backend/app/auth/schemas.py`, `backend/app/auth/routes.py`, `backend/app/auth/tokens.py`, `backend/app/auth/onboarding.py`, `backend/app/core/errors.py`, `backend/app/core/ratelimit.py`, `backend/app/models/enums.py`
- `frontend/lib/api/types.ts` (L174–203), `frontend/lib/api/endpoints.ts`, `frontend/lib/api/mock/index.ts` (L344–384), `frontend/components/auth/GuardianGate.tsx` (`POLL_MS = 15_000`, pauses while hidden), `frontend/lib/api/errors.ts`, `frontend/lib/api/client.ts`
- `backend/tests/integration/conftest.py` (rolled-back transaction), `test_rls.py`, `test_token_scope.py`
- PostgreSQL 17.6 docs: `ddl-rowsecurity.html`, `sql-createpolicy.html`, `ddl-partitioning.html`, `sql-altertable.html`

## 1. Scope

Build, in `backend/` + one new migration, the parental-consent gate and the RBAC dependencies that the tutor/quiz/reports work will hang off (PRD FR-A1/A2/A3 §4.2/§4.3; TDD §3.1):

1. `backend/app/auth/dependencies.py` — `require_role(*roles)`, `require_subject_scope(subject_id)`, `require_guardian_verified()` — all wrapping the existing `authenticated` (KAN-10).
2. Student-side gate: `POST /api/auth/guardian/invite`, `GET /api/auth/guardian/status`.
3. Parent side: `POST /api/auth/guardian/confirm`.
4. One new migration: partition RLS hardening for `audit_log_default` / `api_request_log_default` + the guardian SECURITY DEFINER functions.
5. Reconcile the `app_user_insert` policy file to the stricter live policy.
6. `backend/app/core/errors.py` — new AppError factories. `backend/app/core/ratelimit.py` — new buckets.

**Explicitly OUT of scope (do not build):** auth core (KAN-10 — wraps it, does not touch it), 2FA/email/password-reset (Muneeb), the whole frontend (Yahya — we only *match* the existing client contract), tutor/assessment/quiz/reports **features** (other teammates — this plan builds the *gate dependency* and proves it with a test-mounted router, because those routers do not exist yet), Classroom Spaces endpoints (scope D — **DEFERRED, pending Yahya's confirmation**, see §8; only the `require_subject_scope()` dependency is built), and the subscription endpoints `GET /api/subscription` + `POST /api/subscription/select` (**UNOWNED — flagged, not built**, see §8 Open Questions).

## 2. Grounding & key decisions

Every decision below is grounded in (a) prd.md, (b) tdd.md, (c) the applied SQL in `supabase/migrations/`, (d) existing repo conventions, or (e) official PostgreSQL docs. No decision is invented.

### 2.1 Foundation rules (non-negotiable, from the applied code + plan.txt)
1. **Bind the acting user per transaction** via `SET LOCAL app.current_user_id` (`set_current_user_id`). Unset ⇒ zero rows. A mid-request `commit()` discards it, so nothing may commit before reads that depend on it.
2. **Never use `get_service_db`/`service_engine` in a request path.** Pre-auth/service-role reads go through narrow SECURITY DEFINER functions (migration 20260802140000). The guardian flow follows this: the only privileged reads/writes are two new narrow functions (Phase 1).
3. **Never connect as `postgres`.** `app_backend` (NOBYPASSRLS) everywhere; startup asserts this.
4. **Errors branch on `code`, never on `message`.**
5. **Commit before raising if a write must survive the error** — the confirm write is ordered last so the success path is the only one that writes (see 2.6).

### 2.2 Answers to the 5 open questions (decided here; each grounded)
1. **`guardian/confirm` request body = `{ "invite_token": "..." }` — CONFIRMED.** The body is not specified in tdd.md; Yahya's frontend assumes it (`types.ts` L182–191 ASSUMPTION comment; `mock/index.ts` L363–379; decision 6: "a token is always a body field"). It is *required*, not cosmetic: a parent with two children must say which link is being confirmed. The token is an opaque random string, stored **hashed** in `auth_token` with `kind = 'guardian_invite'` (the enum value already exists, `enums.py` L56), issued at invite time, delivered out-of-band by email, one-time-use, TTL 7 days (assumption §8). A parent who signs up after the invite still works: the token resolves to the student, and the pending link already stores `parent_id`.
2. **`GUARDIAN_ALREADY_LINKED` — 409, returned by `POST /api/auth/guardian/confirm`** when the target link is already `verified`, **and by `POST /api/auth/guardian/invite`** when the student already has a verified link. The client already models the code (`errors.ts` L21) and the mock returns `fail(409, 'GUARDIAN_ALREADY_LINKED')` on confirm when `status === 'verified'` (mock L371). Confirmed: **409**, per the client's assumption.
3. **15 s poll on `GET /api/auth/guardian/status` against the in-process limiter — ACCEPTABLE, with a dedicated bucket.** Worst case is 4 req/min per client (a visible tab); the poll pauses while hidden (`GuardianGate.tsx` L113). The in-process fixed-window limiter keys by client host (`ratelimit.py` L47–53), which is per-connection in FYP deployment. Add `GUARDIAN_STATUS_LIMIT = Limit(max_requests=60, window_seconds=60)` — 15× headroom, and a generous limit is intentional because this endpoint is authenticated and low-risk (it is *not* a brute-force surface).
4. **Partitions + RLS — requires a migration (DONE in 20260802150000).** The enable/force loop skips `%_default` tables (`rls_policies.sql` L131 `tablename NOT LIKE '%_default'`), so `audit_log_default` and `api_request_log_default` have RLS **disabled**. PostgreSQL 17 docs + community verification: `ENABLE ROW LEVEL SECURITY` on a partitioned parent does **not** cascade; each partition has its own `pg_class.relrowsecurity`, and policies are per-table (`CREATE POLICY` Notes: "policies are table-specific"). Access *through the parent* applies parent policies, but **direct access to a partition evaluates only that partition's policies** — with RLS disabled on the partition, an `app_backend` connection can `SELECT * FROM audit_log_default` and read the whole audit trail, defeating `audit_admin_read`. Fix in the new migration: `ENABLE` + `FORCE` RLS on both default partitions **with no policies on them**, so direct access is default-deny while parent-scoped reads/writes keep working through the parent's existing policies. Document that any future partition needs the same two `ALTER TABLE` statements. **Implementation note:** the live database had already been hardened (`relrowsecurity`/`relforcerowsecurity` = true on both default partitions — probed before applying), so the migration's `ALTER`s are no-ops there but are required for fresh environments; direct `SELECT count(*)` on `audit_log_default`/`api_request_log_default` as a bound non-admin returns 0 rows (asserted in `test_rls.py`).
5. **`app_user_insert ... WITH CHECK (true)` vs the live policy — the LIVE policy was the permissive one; the migration reconciles it to the owner-scoped form (DONE in 20260802150000).** `test_rls.py`/`test_token_scope.py` did NOT record a stricter live policy: a probe against the live database before applying the migration showed `app_user_insert` was `WITH CHECK (true)` and an unbound insert SUCCEEDED (the exact gap this work closes). The plan owns the schema: the migration re-asserts the policy as `CREATE POLICY app_user_insert ... FOR INSERT TO app_backend WITH CHECK (id = app.current_user_id())` (idempotent) so a fresh environment AND the live database match, and `rls_policies.sql` L154–155 was edited to the same form. `register()` already binds the new id before insert (`service.py`), so nothing breaks. After applying, an unbound `app_user` insert is refused (`psycopg.errors.InsufficientPrivilege ... violates row-level security policy`) — asserted in `test_rls.py` (Phase 5).

### 2.3 The three RBAC dependencies (grounded in prd §4.2 matrix)
- `require_role(*roles)`: extends `AuthContext` with `role` (the `authenticated` dependency's identity query becomes `SELECT status, role FROM app_user ...` — additive, one query per request, runs under `app_user_self_read`). Rejects with **403 FORBIDDEN_SCOPE** when the role is not allowed. Non-admins are never allowed via roles they lack — role, not subject, is the first gate.
- `require_subject_scope(subject_id)`: teacher-only. Verifies a `teacher_subject_scope` row `(teacher_id = current_user, subject_id = :subject_id)` exists — readable under `tss_read` (`rls_policies.sql` L246–248) with no privileged connection. 0 rows ⇒ **403 FORBIDDEN_SCOPE**. **Built now, wired by the classroom P1 when Yahya confirms scope D.**
- `require_guardian_verified()`: the gate. After `authenticated`:
  - Not a student ⇒ pass (teachers/parents/admins are never gated).
  - Student with `class_level ∈ {9, 10}` and `guardian_status != 'verified'` ⇒ **403 GATE_PENDING**.
  - Class 11–12 ⇒ **never gated** (prd §4.3).
  - The decision is a **pure function** `is_guardian_gate_pending(is_student, class_level, guardian_status)` (Phase 3) so it is unit-testable with no database. `student_profile` + `guardian_link` are read under RLS as the student (both policies allow self-read) — **no privileged connection**.
  - Must be applied to `/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, `/api/reports/*`. Since those routers do not exist in this repo yet, the plan proves the gate with a **test-mounted router** in the authz-matrix test (Phase 5) and exports the dependency for the future routers.

### 2.4 OOB model (v0.3.2 decisions 1 + 5, NOT re-litigated)
The redeemable-code flow was **rejected** in v0.3.2 (decision 1): a code the student types is not out-of-band. The parent **signs up first** and confirms from their own authenticated account (decision 5). The invitation travels by email; the token arrives by email. This is why:
- invite is `role=student`, confirm is `role=parent` (a student can never confirm their own gate — blocked at role, and `ck_guardian_not_self` blocks self-links at the schema).
- the invite response contains **no token** (it goes by email); the mock's `invite-<student-id>` is a dev convenience only.
- confirm consumes the token (one-time-use) and flips the link to `verified` through a SECURITY DEFINER function (2.6).

### 2.5 Guardian status semantics (grounded in the client contract)
- No link ⇒ `status = null` (NOT the string `"none"` — `me()` already does this, `service.py` L359–362, and the client types `GuardianStatus | null`).
- `revoked` must pass through unchanged (real value, not flattened).
- `required = is_student AND class_level ∈ {9,10}` — shared pure helper so `me()` and `/guardian/status` cannot drift.
- `parent_email` is **masked** in the API response to match the mock (`mock/index.ts` L383 `maskEmail`).
- A student may have several link rows; pick the representative with `verified` winning, latest `created_at` otherwise (reuses the `me()` LATERAL logic, `service.py` L330–336).

### 2.6 Confirm as a narrow SECURITY DEFINER function (grounded in 20260802140000)
`confirm` must (a) read the student's `auth_token` by hash — the parent cannot read the student's token under `auth_token_owner`; (b) read the student's `full_name` — the parent cannot read the student's `app_user` row under `app_user_self_read`; (c) flip the link to `verified` and revoke the token atomically. All three need a privileged path. The applied-SQL precedent (20260802140000) is narrow SECURITY DEFINER functions with `REVOKE ... FROM PUBLIC; GRANT ... TO app_backend`. So:

`app.confirm_guardian_link(p_parent uuid, p_token_hash text)` returns `TABLE(status guardian_status, student_name text)`:
1. find the token by hash where `kind = 'guardian_invite'` and not revoked and not expired;
2. find the link `(student_id = token.user_id, parent_id = p_parent)`;
3. if already `verified` → return `('verified', name)` (Python maps to 409);
4. else `UPDATE guardian_link SET status='verified', verification_method='oob_email', verified_at=now()` for that link, `UPDATE auth_token SET revoked=true` for the token, and return `('verified', student_name)`.

The write is the *last* statement; the Python caller raises `RATE_LIMITED`/validation errors **before** calling it, so no write is made that must survive an error. This function is the database backstop for "student cannot confirm own gate": a student cannot call it as a parent (role gate in Python) and cannot forge a token (hashed, one-time).

## 3. Exact endpoint contracts (immutable — three teammates build against these)

```
POST /api/auth/guardian/invite   (auth: Bearer, role=student)
req  { "parent_email": "p@example.com" }
200  { "invite_sent": true, "parent_email": "p***@example.com", "status": "pending" }
422  SELF_LINK_FORBIDDEN        parent_email == student's own email
422  GUARDIAN_NOT_FOUND         no parent account with that email      [NEW code — flag for frontend]
409  GUARDIAN_ALREADY_LINKED    a verified link already exists

POST /api/auth/guardian/confirm  (auth: Bearer, role=parent)
req  { "invite_token": "..." }
200  { "status": "verified", "student_name": "Ayesha" }
403  FORBIDDEN_SCOPE            role != parent
400  INVALID_TOKEN              unknown / expired / revoked / wrong-kind token, or no matching pending link
409  GUARDIAN_ALREADY_LINKED    target link already verified
422  SELF_LINK_FORBIDDEN        parent == student (unreachable; kept for parity)

GET  /api/auth/guardian/status  (auth: Bearer, role=student)
200  { "required": true,
       "status": "pending" | "verified" | "revoked" | null,
       "parent_email": "p***@example.com" | null,
       "invited_at": "2026-08-03T10:00:00Z" | null }
```

Error envelope for ALL non-2xx (existing shape, `errors.py` L60–63):
```
{ "error": { "code": "...", "message": "...", "details": {...} } }
```
New codes: `GATE_PENDING` (403) · `FORBIDDEN_SCOPE` (403) · `SELF_LINK_FORBIDDEN` (422) · `GUARDIAN_ALREADY_LINKED` (409) · `INVALID_TOKEN` (400) · `GUARDIAN_NOT_FOUND` (422). Existing `VALIDATION_ERROR`/`UNAUTHENTICATED`/`RATE_LIMITED` unchanged.

Rate limits (`ratelimit.py`, in-process fixed-window — same interface as LOGIN/REGISTER/REFRESH):
- `GUARDIAN_STATUS_LIMIT = Limit(max_requests=60, window_seconds=60)` — absorbs the 15 s poll with 15× headroom.
- `GUARDIAN_INVITE_LIMIT  = Limit(max_requests=5,  window_seconds=300)` — mirrors REGISTER.
- `GUARDIAN_CONFIRM_LIMIT = Limit(max_requests=10, window_seconds=60)` — token-guessing is a brute-force surface; mirrors LOGIN.

## 4. File-by-file implementation phases (each independently committable)

### Phase 1 — Schema: new migration + reconcile `app_user_insert` (commit 1)
Files:
- `supabase/migrations/20260802150000_guardian_gate_and_partition_rls.sql` (NEW)
- `supabase/migrations/20260801120100_rls_policies.sql` (edit L154–155)

BEFORE (`rls_policies.sql` L152–155):
```sql
-- Registration happens before a session exists, so INSERT is unrestricted here;
-- the API layer owns validation.
CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend WITH CHECK (true);
```
AFTER:
```sql
-- Owner-scoped, matching the live database (register() binds the new id first,
-- so an unbound insert is refused — see test_rls.py / test_token_scope.py).
CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend WITH CHECK (id = app.current_user_id());
```

New migration contents (implemented — full source in the file, exact):
```sql
-- Partition RLS: enable/force on the DEFAULT partitions (the enable loop in
-- 20260801120100 skips *_default, so these had RLS disabled — direct SELECT
-- bypassed audit_admin_read). No policies here => default-deny on direct
-- access; parent-scoped access keeps using the parent's policies. (Live DB was
-- already hardened; these ALTERs are idempotent no-ops there, required for
-- fresh environments.)
ALTER TABLE public.audit_log_default      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log_default      FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.api_request_log_default ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_request_log_default FORCE  ROW LEVEL SECURITY;
-- NOTE: any future partition needs the same two statements.

-- Reconcile app_user_insert to the owner-scoped form (idempotent; live DB had
-- the permissive WITH CHECK (true) and was reconciled by this file).
DROP POLICY IF EXISTS app_user_insert ON public.app_user;
CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend
  WITH CHECK (id = app.current_user_id());

-- Narrow SECURITY DEFINER confirm (pattern: 20260802140000). Atomic: consumes
-- the one-time token and flips a pending link to verified in one statement (the
-- data-modifying CTEs run exactly once). Returns the PRE-transition status so
-- the caller can tell "just verified" (200) from "already verified" (409):
--   * token unknown / expired / revoked       -> 0 rows   (400 INVALID_TOKEN)
--   * link already verified                   -> ('verified', name); token NOT
--                                                consumed (409 path)
--   * link pending                            -> flips + consumes token; returns
--                                                ('pending', name) — pre-transition
--   * link revoked                            -> 0 rows (re-invite flips back first)
-- `l` is referenced by the data-modifying CTE `upd`, so PostgreSQL MATERIALIZES
-- it before the update runs — the returned status is the pre-update value.
CREATE OR REPLACE FUNCTION app.confirm_guardian_link(
  p_parent uuid, p_token_hash text
) RETURNS TABLE (status guardian_status, student_name text)
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  WITH t AS (
    SELECT id, user_id FROM public.auth_token
    WHERE token_hash = p_token_hash
      AND kind = 'guardian_invite' AND revoked = false
      AND expires_at > now()
  ), l AS (
    SELECT id, status, student_id FROM public.guardian_link
    WHERE student_id = (SELECT user_id FROM t)
      AND parent_id = p_parent
  ), upd AS (
    UPDATE public.guardian_link g
       SET status = 'verified',
           verification_method = 'oob_email',
           verified_at = now()
      FROM l
     WHERE g.id = l.id AND l.status = 'pending'
    RETURNING g.id
  ), tok AS (
    -- Consumed only when a transition actually happened (upd non-empty), so the
    -- 409 path leaves the token untouched.
    UPDATE public.auth_token a SET revoked = true
      FROM t, upd
     WHERE a.id = t.id
    RETURNING a.id
  )
  SELECT l.status, u.full_name
    FROM l JOIN public.app_user u ON u.id = l.student_id
   WHERE l.status IN ('pending', 'verified')
  LIMIT 1;
$$;

-- Parent email for the status endpoint (student cannot read the parent's
-- app_user row under RLS). 'verified' wins, latest created_at otherwise.
CREATE OR REPLACE FUNCTION app.lookup_guardian_parent_email(p_student uuid)
RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.email FROM public.guardian_link g
  JOIN public.app_user u ON u.id = g.parent_id
  WHERE g.student_id = p_student
  ORDER BY (g.status = 'verified') DESC, g.created_at DESC
  LIMIT 1;
$$;

-- Parent id by email for invite (student cannot read the parent's app_user row
-- under RLS). Active parent only — never linkable otherwise (caller: 422
-- GUARDIAN_NOT_FOUND when it returns nothing). Open Q6 resolved: parent account
-- must exist.
CREATE OR REPLACE FUNCTION app.lookup_parent_id_by_email(p_email text)
RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.id FROM public.app_user u
   WHERE lower(u.email) = lower(p_email)
     AND u.role = 'parent' AND u.status = 'active' AND u.deleted_at IS NULL
   LIMIT 1;
$$;

REVOKE ALL ON FUNCTION app.confirm_guardian_link(uuid, text)      FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_guardian_parent_email(uuid)     FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_parent_id_by_email(text)        FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION app.confirm_guardian_link(uuid, text)  TO app_backend;
GRANT  EXECUTE ON FUNCTION app.lookup_guardian_parent_email(uuid) TO app_backend;
GRANT  EXECUTE ON FUNCTION app.lookup_parent_id_by_email(text)    TO app_backend;
```
Commit 1: `feat(db): guardian confirm/parent-email lookups + partition RLS + reconcile app_user_insert`

### Phase 2 — Error codes + rate-limit buckets (commit 2)
Files:
- `backend/app/core/errors.py` — factories:
```python
def forbidden_scope(message: str = "This account cannot do that.") -> AppError:
    return AppError(code="FORBIDDEN_SCOPE", message=message, status_code=403)

def gate_pending(message: str = "Parental consent is pending.") -> AppError:
    return AppError(code="GATE_PENDING", message=message, status_code=403)

def self_link_forbidden(message: str = "A parent cannot be linked to themselves.") -> AppError:
    return AppError(code="SELF_LINK_FORBIDDEN", message=message, status_code=422)

def guardian_already_linked(message: str = "A guardian is already linked.") -> AppError:
    return AppError(code="GUARDIAN_ALREADY_LINKED", message=message, status_code=409)

def invalid_token(message: str = "This link is invalid or has expired.") -> AppError:
    return AppError(code="INVALID_TOKEN", message=message, status_code=400)

def guardian_not_found(message: str = "No parent account uses that email.") -> AppError:
    return AppError(code="GUARDIAN_NOT_FOUND", message=message, status_code=422)
```
- `backend/app/core/ratelimit.py` — add the three limits from §3.
Commit 2: `feat(be): guardian error codes + rate-limit buckets`

### Phase 3 — Pure gate logic + the three RBAC dependencies (commit 3)
Files:
- `backend/app/auth/gate.py` (NEW) — pure, no DB/settings imports (mirrors `onboarding.py`):
```python
def is_guardian_gate_pending(*, is_student: bool, class_level: int | None,
                             guardian_status: str | None) -> bool:
    # prd §4.3: Classes 9-10 only; 11-12 never gated. `revoked` and `null` and
    # `pending` are all gated; only `verified` passes. Fails closed.
    if not is_student:
        return False
    if class_level not in (9, 10):
        return False
    return guardian_status != "verified"
```
- `backend/app/auth/dependencies.py` — `AuthContext` gains `role: str`; `authenticated`'s identity query becomes `SELECT status, role FROM app_user WHERE id = :uid AND deleted_at IS NULL`; then:
```python
def require_role(*roles: str):
    def _dep(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
        if ctx.role not in roles:
            raise forbidden_scope()
        return ctx
    return _dep

def require_subject_scope(subject_id: UUID):
    def _dep(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
        # readable under tss_read; 0 rows => teacher doesn't teach this subject
        row = ctx.session.execute(
            text("SELECT 1 FROM teacher_subject_scope WHERE teacher_id = :tid AND subject_id = :sid"),
            {"tid": ctx.user_id, "sid": subject_id},
        ).one_or_none()
        if row is None:
            raise forbidden_scope()
        return ctx
    return _dep

def require_guardian_verified(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
    # one query: student_profile.class_level + representative guardian status,
    # both under RLS as the student. Pure decision in gate.py.
    ...
```
- `backend/app/auth/service.py` — `me()` delegates `guardian_required`/gate derivation to `gate.py` (no behavior change, removes drift).
Commit 3: `feat(be): RBAC dependencies (role, subject scope, guardian gate)`

### Phase 4 — Guardian service, schemas, routes, token issuance (commit 4)
Files:
- `backend/app/auth/tokens.py` — `issue_guardian_invite_token(session, student_id, ttl_seconds=7*86400) -> str` returning the plaintext; stores via the existing `_insert_token` path (`app.insert_auth_token`), `kind=TokenKind.guardian_invite`. NOT the `issue_challenge_token` path (that is 2FA-kind-restricted by design, `tokens.py` L183–184).
- `backend/app/auth/schemas.py` — `GuardianInviteRequest { parent_email }`, `GuardianInviteResponse { invite_sent, parent_email, status }`, `GuardianConfirmRequest { invite_token }`, `GuardianConfirmResponse { status, student_name }`, `GuardianStatusResponse { required, status, parent_email, invited_at }` — all mirroring `types.ts` L174–203 exactly.
- `backend/app/auth/service.py` — `guardian_invite(db, student_id, payload)` (validate self-link → 422; find parent by email via a narrow lookup — see note; create pending link + issue token; verified-link exists → 409), `guardian_status(db, student_id)` (gate.py decision + link representative + masked parent email via `app.lookup_guardian_parent_email`), `guardian_confirm(db, parent_id, payload)` (resolve via `app.confirm_guardian_link`; map `already-verified` → 409, no-link → 400 INVALID_TOKEN).
- `backend/app/auth/routes.py` — three endpoints, each with `enforce(request, bucket=..., limit=...)` and role deps. **No route touches `get_service_db`.**
Commit 4: `feat(be): guardian invite/status/confirm endpoints`

> **Note for Phase 4 (RESOLVED — implemented):** invite resolves the parent's id by email via the sibling narrow function `app.lookup_parent_id_by_email(text)` added to the Phase 1 migration (id only when `role='parent'` and `status='active'`). **Decision 6: require the parent account to exist** (matches "parent signs up first", decision 5); a missing account returns 422 `GUARDIAN_NOT_FOUND`. An unknown student's own email is never probed (self-link check compares against the student's own `app_user.email`, no oracle).

### Phase 5 — Tests + verification (commit 5)
Files:
- `backend/tests/unit/test_gate.py` — `is_guardian_gate_pending` matrix: student 9/10 with null/pending/revoked ⇒ gated; verified ⇒ pass; 11/12 never; teacher/parent/admin never. **No database.**
- `backend/tests/integration/test_guardian_flow.py` — full flows inside the rolled-back transaction (`conftest.py`): invite → confirm → status happy path; self-link 422; student confirm ⇒ 403 FORBIDDEN_SCOPE; GUARDIAN_NOT_FOUND; GUARDIAN_ALREADY_LINKED (both endpoints); INVALID_TOKEN (unknown + consumed token replay); status null when absent; `revoked` passthrough; masked email shape.
- `backend/tests/integration/test_authz_matrix.py` — the **role × endpoint matrix**. Builds a small FastAPI app in the test (conftest patches `SessionLocal` in both modules) that wires the three real dependencies onto representative paths: `/api/tutor/ask`, `/api/practice/adaptive`, `/api/quiz/{id}/attempts/start`, `/api/reports/weekly` (gate), `require_subject_scope` on a teacher path, plus the three guardian routes. Asserts, per role × endpoint, the exact status. This is how "gate per endpoint" is proven while the real routers do not exist yet.
- `backend/tests/integration/test_rls.py` — add: unbound `app_user` insert refused (open Q5); parent with verified link can `SELECT` the student's `student_profile` (progress) but **0 rows** on `message`/`chat_session` (prd §4.2 chat boundary); `SELECT * FROM audit_log_default` returns 0 rows for non-admin `app_backend` (Phase 1 partition fix).
Commit 5: `test(be): guardian gate + RBAC authz-matrix + partition RLS coverage`

## 5. Stress-test report

### PASS 1 (attempt to break the plan)
- **Missing gate on an endpoint?** The four gated families are enumerated (`/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, `/api/reports/*`). Their routers don't exist in this repo, so the gate is proven with a test-mounted router and the dependency is exported for the future routers. The guardian endpoints themselves must NOT be gated (a gated student must reach `/guardian/status`); they are role-gated instead.
- **Parent reading chat content?** `message`/`chat_session` policies are student-owner-only (`message_owner` EXISTS chat_session.student_id = current_user). A parent is never `current_user` of the child ⇒ 0 rows, asserted in Phase 5. Progress (student_profile) is parent-readable via `is_verified_guardian_of` — intended. No new route exposes chat to parents.
- **Student self-verify?** Three independent blockers: confirm is `role=parent` (403), `ck_guardian_not_self` blocks self-links at schema, and the token is hashed + one-time (can't be forged/replayed). RLS `guardian_link_update` (L202–204) has no WITH CHECK and *would* allow a participant to flip `verified` via raw SQL — **contained** because the API is the only reachable writer and the confirm write runs through `app.confirm_guardian_link`, but recorded here as the one place where the DB is defense-in-depth rather than the control.
- **Teacher subject scope?** `require_subject_scope` checks `teacher_subject_scope` under `tss_read`; 0 rows ⇒ FORBIDDEN_SCOPE. Teachers have no tutor access (v0.3.2: tdd won over prd).
- **Unbound user / commit discarding SET LOCAL?** No new route opens a privileged connection; all reads run on the `authenticated` session after binding. Confirm's write is the last statement; nothing commits before reads that depend on the GUC.
- **Policy vs Python disagreements?** `app_user_insert` mismatch resolved (open Q5). Partition RLS gap resolved (open Q4). No other file/live drift found.
- **API-only gating?** The gate is a FastAPI dependency (application layer) — correct by design because "class 9–10 + unverified" is not expressible as RLS; the DB backstop is that learning data tables are student-owner-only anyway.
- **Contract mismatch with the frontend?** Matched against `types.ts` L174–203, `mock/index.ts` L344–384, `endpoints.ts`, `errors.ts`, `client.ts` GATE_PENDING → `/onboarding/guardian` redirect. Status null / revoked passthrough / 409 code / body keys all match.

### PASS 2 (re-review after fixes)
- Phase 1 reconciles the two schema gaps probed on the live database (app_user_insert file vs live — live was the permissive one and is now hardened; partitions' DEFAULT tables never RLS-enabled). Applied live; `test_rls.py` asserts the fixed state.
- Phase 3 isolates the gate decision as pure logic — `me()` and `/guardian/status` share one helper, so the DoD "class 11–12 never gated" cannot drift between endpoints.
- Phase 4 has **no** `get_service_db` dependency and **no** privileged ORM session (the mock's `invite-<id>` token never enters the API).
- Phase 5 covers every Definition-of-Done line below, including an unbound-insert refusal and a parent-reads-progress-but-never-chat assertion.
- No scope creep: subscription endpoints flagged UNOWNED (not built); Classroom Spaces deferred pending Yahya (only the dep is built).

## 6. Definition of Done (from plan.txt — each asserted in Phase 5)
- [x] Class 9–10 student cannot reach any learning endpoint until a parent confirms ⇒ **403 GATE_PENDING** (authz-matrix, all four gated families).
- [x] Class 11–12 student is NEVER gated (authz-matrix + unit gate matrix).
- [x] A student cannot confirm their own gate by any route (role gate + ck_guardian_not_self + one-time hashed token; integration).
- [x] A parent reads a child's progress but NEVER chat content, asserted per endpoint (RLS: student_profile readable, message/chat_session 0 rows).
- [x] A teacher is confined to subject scope (`require_subject_scope`, unit + integration).
- [x] `guardian.status` is `null` when absent and `revoked` passes through unchanged (integration).
- [x] With `app.current_user_id` unset, every query returns zero rows (existing fail-closed test + new unbound-insert refusal).
- [x] The authz-matrix test covers every role × every endpoint touched (test_authz_matrix.py).
- [x] Pure logic lives in `tests/unit` with NO database (gate.py decision, error codes).
- [x] Integration tests run inside a rolled-back transaction (`conftest.py`).

## 7. Definition of Done — assertable acceptance (run)
```
cd backend
python -m pytest tests/unit -q
python -m pytest tests/integration -q   # needs a live Supabase project with the applied schema
```

## 8. ASSUMPTIONS & OPEN QUESTIONS FOR THE HUMAN

**Assumptions (each must be confirmed or the code will be adjusted):**
1. `GUARDIAN_ALREADY_LINKED` is **409** on both confirm (target already verified) and invite (student already verified) — matches the client's assumption (`errors.ts`), confirmed in §2.2.
2. Invite token TTL = **7 days**; one-time use (revoked on confirm). Email delivery is Muneeb's seam; the API returns no token in the response.
3. The invite requires the parent's account to **already exist** (decision 5: "parent signs up first"); a missing account ⇒ 422 `GUARDIAN_NOT_FOUND` (**new code — Yahya's frontend must render it**; the mock never exercises it).
4. The confirm body is `{ "invite_token": ... }` (open Q1 — **confirmed against the client**, but Yahya should sign off since it is the plan's highest-priority contract item).
5. `GUARDIAN_STATUS_LIMIT = 60/60s` is acceptable for a 15 s poll (open Q3). If the frontend ever opens N visible tabs, N×4 req/min must stay under 60.
6. The parent-email masking format matches `maskEmail` in the mock exactly.
7. RLS `guardian_link_update` is left as-is; `app.confirm_guardian_link` is the enforcement boundary for the verified transition (documented residual risk, PASS 1).
8. `auth_token` insert for the invite runs via the existing `app.insert_auth_token` SECURITY DEFINER function (pre-session pattern); the student is authenticated but the token's `user_id` is the **student** (the gate subject), which the parent resolves by hash at confirm.

**Open questions:**
1. **`guardian/confirm` body — sign-off on `{ "invite_token": ... }`** (highest priority; §2.2 answer 1). The token is required for multi-child parents; if Yahya instead wants keying off the parent's identity alone, the field is dropped and the whole flow simplifies — but that breaks the two-children case.
2. **`GUARDIAN_ALREADY_LINKED` on which endpoints and with what status?** Answered as 409 on confirm + invite (§2.2 answer 2). Confirm Yahya's client handles 409 on invite (mock only models it on confirm).
3. **Polling vs the in-process limiter** (§2.2 answer 3). A single `uvicorn` process makes the in-process counter a real control; N workers ⇒ N× allowance (documented in `ratelimit.py`). Acceptable for the FYP, but confirm the deployment stays single-process, or move the counter to Redis (seam already exists).
4. **Partition RLS (RESOLVED — §2.2 answer 4, built in 20260802150000)** — the migration enables/forces RLS on the two default partitions (default-deny on direct access); applied to the live database and asserted in `test_rls.py`. Confirm the team will ENABLE/FORCE any future partition.
5. **`app_user_insert` reconcile (RESOLVED — §2.2 answer 5, built)** — the migration re-asserts the owner-scoped policy on the live database AND the file L154–155 was corrected to the same form; an unbound insert is now refused (asserted in `test_rls.py`). Confirm no other tooling depends on the permissive form.
6. **Invite when the parent has no account (RESOLVED)** — require the parent to exist: 422 `GUARDIAN_NOT_FOUND` (the default in the note on Phase 4), implemented via `app.lookup_parent_id_by_email`.
7. **UNOWNED endpoints:** `GET /api/subscription` and `POST /api/subscription/select` have no owner in this plan (they belong to the plan-selection track). They are NOT built here; someone must own them (flagging so it is not silently assumed built).
8. **Classroom Spaces (scope D)** — deferred pending Yahya's confirmation. Only `require_subject_scope()` is built now; the space/enrollment endpoints and their wiring are a follow-up phase.
