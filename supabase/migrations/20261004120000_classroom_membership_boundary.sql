-- ============================================================================
-- EduBridge AI — classroom membership boundary (findings B9, B10, B11)
--
-- The classroom tables have existed since the initial schema with policies
-- that the August 2026 review found would not hold (database.md §2.4). No
-- classroom endpoint exists yet, so this is the cheapest moment to close them:
-- the first route built on today's policies would make every one reachable.
--
--   B9  `enrollment_student_join` let a student INSERT an enrolment into ANY
--       space — the join code was an application convention, not a boundary.
--       `enrollment_leave` had no WITH CHECK, so the same UPDATE that "left"
--       could also move the row to another space or clear `left_at`.
--       -> app_backend loses every write on `enrollment`; the only writers are
--          the SECURITY DEFINER functions in 20261004120100.
--   B10 `space_owner_write` was FOR ALL with no role check: a student could
--       create a space with owner_role = 'teacher'.
--       -> INSERT only through app.create_space (role read from the bound
--          session); UPDATE narrowed to (title, status); no DELETE ever.
--   B11 `app.owns_space` ignored `teacher_subject_scope`.
--       -> owner AND active teacher AND an UNREVOKED scope row for the space's
--          subject. Scope is self-declared by app.create_space (owner decision,
--          2026-10-03); an administrator withdraws it with `revoked_at`.
--
-- ⚠️ REVERSES A RECORDED DECISION (database.md:864-868, "join_code_owner stays
--    FOR ALL"). The repository owner reversed it on 2026-10-03: while the owner
--    could INSERT any string, code entropy and "one live code per space" were
--    application promises. Codes are now minted in Python with `secrets` and
--    written only by app.rotate_join_code; the format CHECK and the partial
--    unique index make both properties hold in the database.
--
-- ⚠️ DRY-RUN PRE-CHECKS. Both must return 0 or the constraints below fail:
--      SELECT count(*) FROM join_code;                 -- old codes may not match the format
--      SELECT count(*) FROM classroom_space WHERE owner_role <> 'teacher';
--    Nothing has ever written either table (no classroom route exists).
--
-- IMPACT (every caller of the two helpers changed here, from the migrations):
--   app.owns_space  — enrollment_visible, join_code_owner_read (new),
--                     attempt_teacher_read and attempt_answer_teacher_read
--                     (rls_policies.sql:362, :384; no route reaches them),
--                     plus every classroom function and policy from now on.
--                     It only NARROWS, matching prd.md §4.2 "own subject only".
--   app.teaches_student_subject — coverage_viewers_read, readiness_viewers_read
--                     (rls_policies.sql:406-425). Becomes reachable for the
--                     first time, because classrooms now write scope rows.
--
-- Idempotent (the Supabase CLI does not wrap a file in a transaction): every
-- constraint and policy is guarded or dropped first; CREATE OR REPLACE keeps
-- the existing grants on functions whose signature is unchanged.
-- ============================================================================

-- ── 0. Revocable self-declared scope ───────────────────────────────────────
ALTER TABLE public.teacher_subject_scope ADD COLUMN IF NOT EXISTS revoked_at timestamptz;
REVOKE DELETE ON public.teacher_subject_scope FROM app_backend;
COMMENT ON COLUMN public.teacher_subject_scope.revoked_at IS
  'Set by an administrator to withdraw a self-declared scope. NEVER delete the row: '
  'app.create_space re-declares with ON CONFLICT DO NOTHING, so a deleted row would be '
  're-granted by the teacher''s next classroom.';

-- ── 1. Helpers ─────────────────────────────────────────────────────────────
-- BEFORE (20260801120100:99-107):
--   SELECT EXISTS (SELECT 1 FROM classroom_space s
--                   WHERE s.id = p_space AND s.owner_id = app.current_user_id());
CREATE OR REPLACE FUNCTION app.owns_space(p_space uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.classroom_space s
      JOIN public.app_user u
        ON u.id = s.owner_id AND u.role = 'teacher' AND u.status = 'active'
      JOIN public.teacher_subject_scope t
        ON t.teacher_id = s.owner_id AND t.subject_id = s.subject_id AND t.revoked_at IS NULL
     WHERE s.id = p_space
       AND s.owner_id = app.current_user_id()
  );
$$;

-- BEFORE (20260801120100:81-97): joined teacher_subject_scope with no revocation.
CREATE OR REPLACE FUNCTION app.teaches_student_subject(p_student uuid, p_subject uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.classroom_space s
      JOIN public.enrollment e
        ON e.space_id = s.id AND e.left_at IS NULL
      JOIN public.teacher_subject_scope t
        ON t.teacher_id = s.owner_id AND t.subject_id = s.subject_id AND t.revoked_at IS NULL
     WHERE s.owner_id   = app.current_user_id()
       AND e.student_id = p_student
       AND s.subject_id = p_subject
       AND s.status     = 'active'
  );
$$;

-- NEW. The write predicate: owner of a space that is not archived.
CREATE OR REPLACE FUNCTION app.owns_active_space(p_space uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT app.owns_space(p_space)
     AND EXISTS (SELECT 1 FROM public.classroom_space s
                  WHERE s.id = p_space AND s.status = 'active');
$$;

-- NEW. Set-returning READ predicates, used as `space_id IN (SELECT app.my_…())`.
-- A SECURITY DEFINER function is never inlined, so a per-row helper runs once
-- per ROW; an uncorrelated IN-subquery runs once per QUERY (a hashed subplan).
-- That is the difference between a 300-row roster costing 300 lookups and one.
CREATE OR REPLACE FUNCTION app.my_owned_space_ids() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT s.id
    FROM public.classroom_space s
    JOIN public.app_user u
      ON u.id = s.owner_id AND u.role = 'teacher' AND u.status = 'active'
    JOIN public.teacher_subject_scope t
      ON t.teacher_id = s.owner_id AND t.subject_id = s.subject_id AND t.revoked_at IS NULL
   WHERE s.owner_id = app.current_user_id();
$$;

CREATE OR REPLACE FUNCTION app.my_member_space_ids() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT e.space_id
    FROM public.enrollment e
   WHERE e.student_id = app.current_user_id()
     AND e.left_at IS NULL;
$$;

-- NEW. gate.py in SQL, for the database layer of the Class 9–10 rule.
-- Fails closed: an unbound user, an inactive account or an unknown class level
-- all answer false — an unreadable profile looks exactly like a forgotten
-- binding, and the gate must not treat a 14-year-old as an 18-year-old because
-- a read came back empty (backend/CLAUDE.md §3).
CREATE OR REPLACE FUNCTION app.caller_passes_guardian_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((
    SELECT CASE
             WHEN u.role <> 'student'        THEN true
             WHEN sp.class_level IN (11, 12) THEN true
             ELSE EXISTS (SELECT 1 FROM public.guardian_link g
                           WHERE g.student_id = u.id AND g.status = 'verified')
           END
      FROM public.app_user u
      LEFT JOIN public.student_profile sp ON sp.user_id = u.id
     WHERE u.id = app.current_user_id()
       AND u.status = 'active'
       AND u.deleted_at IS NULL
  ), false);
$$;

-- ── 2. classroom_space (B10) ───────────────────────────────────────────────
DO $$ BEGIN
  -- Parents no longer create spaces (prd.md §4.2, v0.3.5; tdd.md:334). The enum
  -- keeps 'parent' because dropping an enum value is not worth the migration;
  -- the CHECK makes the decision a database fact.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_space_owner_is_teacher') THEN
    ALTER TABLE public.classroom_space
      ADD CONSTRAINT ck_space_owner_is_teacher CHECK (owner_role = 'teacher');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_space_title') THEN
    ALTER TABLE public.classroom_space
      ADD CONSTRAINT ck_space_title CHECK (char_length(btrim(title)) BETWEEN 1 AND 120);
  END IF;
END $$;

-- BEFORE (20260801120100:269-272):
--   CREATE POLICY space_owner_write ON classroom_space FOR ALL TO app_backend
--     USING (owner_id = app.current_user_id())
--     WITH CHECK (owner_id = app.current_user_id());
DROP POLICY IF EXISTS space_owner_write  ON public.classroom_space;
DROP POLICY IF EXISTS space_owner_update ON public.classroom_space;
CREATE POLICY space_owner_update ON public.classroom_space
  FOR UPDATE TO app_backend
  USING (app.owns_space(id))
  WITH CHECK (app.owns_space(id));

-- INSERT only via app.create_space. No DELETE ever: archiving is `status`.
REVOKE INSERT, UPDATE, DELETE ON public.classroom_space FROM app_backend;
GRANT UPDATE (title, status) ON public.classroom_space TO app_backend;
-- space_visible (20260801120100:261-267) is UNCHANGED on purpose: a de-scoped
-- teacher still sees the row, so the interface can explain the revocation.
-- Every CONTENT policy goes through the scope-checking helpers.

-- ── 3. join_code (reverses database.md:864-868) ────────────────────────────
DO $$ BEGIN
  -- 32 symbols (no I, O, 0, 1), length 8: 32^8 = 2^40 codes.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_join_code_format') THEN
    ALTER TABLE public.join_code
      ADD CONSTRAINT ck_join_code_format CHECK (code ~ '^[A-HJ-NP-Z2-9]{8}$');
  END IF;
END $$;
-- One live code per space, as a database fact rather than an application habit.
DROP INDEX IF EXISTS public.ix_join_code_active;
CREATE UNIQUE INDEX IF NOT EXISTS uq_join_code_one_live
  ON public.join_code (space_id) WHERE revoked = false;

-- BEFORE (20260801120100:275-278):
--   CREATE POLICY join_code_owner ON join_code FOR ALL TO app_backend
--     USING (app.owns_space(space_id) OR app.is_admin())
--     WITH CHECK (app.owns_space(space_id));
DROP POLICY IF EXISTS join_code_owner      ON public.join_code;
DROP POLICY IF EXISTS join_code_owner_read ON public.join_code;
CREATE POLICY join_code_owner_read ON public.join_code
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin()));
REVOKE INSERT, UPDATE, DELETE ON public.join_code FROM app_backend;

-- ── 4. enrollment (B9) ─────────────────────────────────────────────────────
-- `removed_at`: the state machine tdd.md:773 already names (joined -> left |
-- removed). A removed student cannot rejoin with the code; one who left can.
-- `muted_at`: written by the chat phase. Added now so app.space_people keeps a
-- stable signature (a changed RETURNS TABLE means DROP + CREATE + re-grant).
ALTER TABLE public.enrollment ADD COLUMN IF NOT EXISTS removed_at timestamptz;
ALTER TABLE public.enrollment ADD COLUMN IF NOT EXISTS muted_at   timestamptz;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_enrollment_removed_has_left') THEN
    ALTER TABLE public.enrollment
      ADD CONSTRAINT ck_enrollment_removed_has_left
      CHECK (removed_at IS NULL OR left_at IS NOT NULL);
  END IF;
END $$;

-- BEFORE (20260801120100:289-296):
--   enrollment_student_join FOR INSERT WITH CHECK (student_id = app.current_user_id())  -- ANY space
--   enrollment_leave FOR UPDATE USING (student_id = app.current_user_id()
--                                      OR app.owns_space(space_id))                    -- no WITH CHECK
DROP POLICY IF EXISTS enrollment_student_join ON public.enrollment;
DROP POLICY IF EXISTS enrollment_leave        ON public.enrollment;
REVOKE INSERT, UPDATE, DELETE ON public.enrollment FROM app_backend;
-- enrollment_visible (20260801120100:281-287) is unchanged; its owns_space
-- branch now carries the B11 scope check.

-- ── 5. Grants and comments (C5) ────────────────────────────────────────────
-- Granted to app_backend because POLICIES call them, and a policy is evaluated
-- with the privileges of the role running the query: without EXECUTE it would
-- error rather than deny (20260816190000:41-45).
REVOKE ALL ON FUNCTION app.owns_active_space(uuid)          FROM PUBLIC;
REVOKE ALL ON FUNCTION app.my_owned_space_ids()             FROM PUBLIC;
REVOKE ALL ON FUNCTION app.my_member_space_ids()            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.caller_passes_guardian_gate()    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.owns_active_space(uuid)       TO app_backend;
GRANT EXECUTE ON FUNCTION app.my_owned_space_ids()          TO app_backend;
GRANT EXECUTE ON FUNCTION app.my_member_space_ids()         TO app_backend;
GRANT EXECUTE ON FUNCTION app.caller_passes_guardian_gate() TO app_backend;

COMMENT ON FUNCTION app.owns_space(uuid) IS
  'RLS helper (enrollment_visible, quiz attempt teacher reads) and classroom service '
  'pre-checks. Owner AND active teacher AND an unrevoked teacher_subject_scope row for '
  'the space''s subject (finding B11).';
COMMENT ON FUNCTION app.teaches_student_subject(uuid, uuid) IS
  'RLS helper (coverage_viewers_read, readiness_viewers_read). Honours '
  'teacher_subject_scope.revoked_at.';
COMMENT ON FUNCTION app.owns_active_space(uuid) IS
  'RLS write predicate for owner content (announcement, assignment, material) and '
  'classroom service pre-checks: app.owns_space AND status = active, so an archived '
  'classroom is read-only.';
COMMENT ON FUNCTION app.my_owned_space_ids() IS
  'RLS read predicate, set form (evaluated once per query): spaces the caller owns '
  'with an unrevoked subject scope.';
COMMENT ON FUNCTION app.my_member_space_ids() IS
  'RLS read predicate, set form (evaluated once per query): spaces the caller is '
  'ACTIVELY enrolled in.';
COMMENT ON FUNCTION app.caller_passes_guardian_gate() IS
  'POST /api/spaces/join (app.join_space_by_code) and the classroom chat insert policy. '
  'gate.py in SQL, anchored on app.current_user_id(); fails closed.';
