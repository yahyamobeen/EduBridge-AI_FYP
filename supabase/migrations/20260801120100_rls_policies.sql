-- ============================================================================
-- EduBridge AI — Row Level Security (defense in depth)
-- Implements : prd.md §4.2 RBAC matrix, §26 minors' data; tdd.md §6.7
--
-- HOW THIS WORKS
--   Authentication is application-managed (own JWT), so Supabase's auth.uid()
--   is NOT available. Instead FastAPI opens a transaction and sets:
--
--       SET LOCAL app.current_user_id = '<uuid-from-our-jwt>';
--
--   Policies read that via app.current_user_id().
--
-- WHY A DEDICATED ROLE
--   Table OWNERS bypass RLS by default, and superusers always bypass it.
--   FastAPI therefore connects as app_backend (NOBYPASSRLS) and every table
--   is set to FORCE ROW LEVEL SECURITY. Without this, policies silently do
--   nothing — the single most common RLS mistake.
--
--   Background jobs that legitimately need full access (ETL, sweeper,
--   reconciliation) connect as the owner/service role instead.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Backend role. Set its password OUT OF BAND — never commit a password.
--   ALTER ROLE app_backend WITH LOGIN PASSWORD '<strong-password>';
-- ----------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
    CREATE ROLE app_backend NOLOGIN NOBYPASSRLS;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public, app TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO app_backend;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_backend;

-- ============================================================================
-- Helper functions
-- SECURITY DEFINER so they can read the tables they check without tripping
-- the very policies that call them (which would recurse).
-- ============================================================================

CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS uuid
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION app.is_admin() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.app_user u
    WHERE u.id = app.current_user_id() AND u.role = 'admin' AND u.status = 'active'
  );
$$;

-- A parent may read a child's data only through a VERIFIED link.
CREATE OR REPLACE FUNCTION app.is_verified_guardian_of(p_student uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.guardian_link g
    WHERE g.parent_id  = app.current_user_id()
      AND g.student_id = p_student
      AND g.status     = 'verified'
  );
$$;

-- A teacher may read a student's data only for subjects they teach AND only
-- for students actively enrolled in one of their spaces (least privilege).
CREATE OR REPLACE FUNCTION app.teaches_student_subject(p_student uuid, p_subject uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.classroom_space s
    JOIN public.enrollment e            ON e.space_id  = s.id AND e.left_at IS NULL
    JOIN public.teacher_subject_scope t ON t.subject_id = s.subject_id
    WHERE s.owner_id   = app.current_user_id()
      AND t.teacher_id = app.current_user_id()
      AND e.student_id = p_student
      AND s.subject_id = p_subject
      AND s.status     = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION app.owns_space(p_space uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.classroom_space s
    WHERE s.id = p_space AND s.owner_id = app.current_user_id()
  );
$$;

CREATE OR REPLACE FUNCTION app.is_enrolled_in(p_space uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.enrollment e
    WHERE e.space_id = p_space
      AND e.student_id = app.current_user_id()
      AND e.left_at IS NULL
  );
$$;

-- ============================================================================
-- Enable + FORCE RLS on every table.
-- Any table without an explicit policy below is DENY-ALL for app_backend.
-- (Also closes Supabase's PostgREST exposure of unprotected public tables.)
-- ============================================================================
DO $$
DECLARE t text;
BEGIN
  FOR t IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename NOT LIKE '%_default'
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('ALTER TABLE public.%I FORCE  ROW LEVEL SECURITY;', t);
  END LOOP;
END
$$;

-- ============================================================================
-- 1. IDENTITY
-- ============================================================================

CREATE POLICY app_user_self_read ON public.app_user
  FOR SELECT TO app_backend
  USING (id = app.current_user_id() OR app.is_admin());

CREATE POLICY app_user_self_update ON public.app_user
  FOR UPDATE TO app_backend
  USING (id = app.current_user_id())
  WITH CHECK (id = app.current_user_id());

-- Registration happens before a session exists, so INSERT is unrestricted here;
-- the API layer owns validation.
CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend WITH CHECK (true);

CREATE POLICY student_profile_read ON public.student_profile
  FOR SELECT TO app_backend
  USING (
    user_id = app.current_user_id()
    OR app.is_verified_guardian_of(user_id)
    OR app.is_admin()
  );

CREATE POLICY student_profile_write ON public.student_profile
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

CREATE POLICY teacher_profile_self ON public.teacher_profile
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id() OR app.is_admin())
  WITH CHECK (user_id = app.current_user_id());

CREATE POLICY parent_profile_self ON public.parent_profile
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id() OR app.is_admin())
  WITH CHECK (user_id = app.current_user_id());

CREATE POLICY admin_profile_self ON public.admin_profile
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id() OR app.is_admin())
  WITH CHECK (app.is_admin());

-- Either side of the link may see it; neither may forge a verified status
-- (the API sets status after out-of-band verification).
CREATE POLICY guardian_link_participants ON public.guardian_link
  FOR SELECT TO app_backend
  USING (
    parent_id  = app.current_user_id()
    OR student_id = app.current_user_id()
    OR app.is_admin()
  );

CREATE POLICY guardian_link_create ON public.guardian_link
  FOR INSERT TO app_backend
  WITH CHECK (
    (student_id = app.current_user_id() OR parent_id = app.current_user_id())
    AND parent_id <> student_id
  );

CREATE POLICY guardian_link_update ON public.guardian_link
  FOR UPDATE TO app_backend
  USING (parent_id = app.current_user_id() OR student_id = app.current_user_id());

CREATE POLICY auth_token_owner ON public.auth_token
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

-- Two-factor (SEC-14): owner-only.
-- Deliberately NO admin policy on these base tables -- admins troubleshoot
-- lockouts through two_factor_status_v, which exposes no secrets or code
-- hashes. RLS is row-level, not column-level, so an admin row policy here
-- would have handed them the secret column too.
CREATE POLICY two_factor_enrollment_owner ON public.two_factor_enrollment
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

CREATE POLICY two_factor_backup_code_owner ON public.two_factor_backup_code
  FOR ALL TO app_backend
  USING (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id());

-- ============================================================================
-- 2. CURRICULUM TAXONOMY — readable by any authenticated user, admin writes
-- ============================================================================
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['board','class_level','subject','subject_group','chapter','slo']
  LOOP
    EXECUTE format($f$
      CREATE POLICY %1$s_read ON public.%1$I
        FOR SELECT TO app_backend
        USING (app.current_user_id() IS NOT NULL);
      CREATE POLICY %1$s_admin_write ON public.%1$I
        FOR ALL TO app_backend
        USING (app.is_admin()) WITH CHECK (app.is_admin());
    $f$, t);
  END LOOP;
END
$$;

CREATE POLICY tss_read ON public.teacher_subject_scope
  FOR SELECT TO app_backend
  USING (teacher_id = app.current_user_id() OR app.is_admin());

CREATE POLICY tss_admin_write ON public.teacher_subject_scope
  FOR ALL TO app_backend
  USING (app.is_admin()) WITH CHECK (app.is_admin());

-- ============================================================================
-- 3. CLASSROOM
-- ============================================================================

CREATE POLICY space_visible ON public.classroom_space
  FOR SELECT TO app_backend
  USING (
    owner_id = app.current_user_id()
    OR app.is_enrolled_in(id)
    OR app.is_admin()
  );

CREATE POLICY space_owner_write ON public.classroom_space
  FOR ALL TO app_backend
  USING (owner_id = app.current_user_id())
  WITH CHECK (owner_id = app.current_user_id());

-- Join codes are never readable by students (they receive the code out of band).
CREATE POLICY join_code_owner ON public.join_code
  FOR ALL TO app_backend
  USING (app.owns_space(space_id) OR app.is_admin())
  WITH CHECK (app.owns_space(space_id));

-- A student sees their own membership; a space owner sees their roster.
CREATE POLICY enrollment_visible ON public.enrollment
  FOR SELECT TO app_backend
  USING (
    student_id = app.current_user_id()
    OR app.owns_space(space_id)
    OR app.is_admin()
  );

CREATE POLICY enrollment_student_join ON public.enrollment
  FOR INSERT TO app_backend
  WITH CHECK (student_id = app.current_user_id());

-- A student may leave; an owner may remove.
CREATE POLICY enrollment_leave ON public.enrollment
  FOR UPDATE TO app_backend
  USING (student_id = app.current_user_id() OR app.owns_space(space_id));

CREATE POLICY announcement_read ON public.announcement
  FOR SELECT TO app_backend
  USING (app.is_enrolled_in(space_id) OR app.owns_space(space_id) OR app.is_admin());

CREATE POLICY announcement_write ON public.announcement
  FOR INSERT TO app_backend
  WITH CHECK (app.owns_space(space_id));

-- ============================================================================
-- 4. ASSESSMENT
-- ============================================================================

CREATE POLICY past_paper_read ON public.past_paper
  FOR SELECT TO app_backend USING (app.current_user_id() IS NOT NULL);
CREATE POLICY past_paper_admin ON public.past_paper
  FOR ALL TO app_backend USING (app.is_admin()) WITH CHECK (app.is_admin());

CREATE POLICY question_read ON public.question
  FOR SELECT TO app_backend USING (app.current_user_id() IS NOT NULL);
CREATE POLICY question_admin ON public.question
  FOR ALL TO app_backend USING (app.is_admin()) WITH CHECK (app.is_admin());

CREATE POLICY question_slo_read ON public.question_slo
  FOR SELECT TO app_backend USING (app.current_user_id() IS NOT NULL);
CREATE POLICY item_difficulty_read ON public.item_difficulty
  FOR SELECT TO app_backend USING (app.current_user_id() IS NOT NULL);
CREATE POLICY slo_freq_read ON public.slo_frequency_cluster
  FOR SELECT TO app_backend USING (app.current_user_id() IS NOT NULL);

-- ---------------------------------------------------------------------------
-- question_key: NO POLICY ON PURPOSE.
-- RLS is enabled + forced, so app_backend can never read answer keys.
-- Grading runs in a background/service role. This is the database-level
-- backstop for NFR-8 "answer keys never leave the server".
-- ---------------------------------------------------------------------------

CREATE POLICY quiz_read ON public.quiz
  FOR SELECT TO app_backend
  USING (
    created_by = app.current_user_id()
    OR (space_id IS NOT NULL AND app.is_enrolled_in(space_id))
    OR app.is_admin()
  );

CREATE POLICY quiz_teacher_write ON public.quiz
  FOR ALL TO app_backend
  USING (created_by = app.current_user_id())
  WITH CHECK (created_by = app.current_user_id());

CREATE POLICY quiz_question_read ON public.quiz_question
  FOR SELECT TO app_backend
  USING (EXISTS (SELECT 1 FROM public.quiz q WHERE q.id = quiz_id));

CREATE POLICY attempt_student_own ON public.quiz_attempt
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

-- A teacher sees attempts only for quizzes in their own space.
CREATE POLICY attempt_teacher_read ON public.quiz_attempt
  FOR SELECT TO app_backend
  USING (
    EXISTS (
      SELECT 1 FROM public.quiz q
      WHERE q.id = quiz_id AND q.space_id IS NOT NULL AND app.owns_space(q.space_id)
    )
    OR app.is_admin()
  );

CREATE POLICY attempt_answer_owner ON public.attempt_answer
  FOR ALL TO app_backend
  USING (EXISTS (
    SELECT 1 FROM public.quiz_attempt a
    WHERE a.id = attempt_id AND a.student_id = app.current_user_id()
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.quiz_attempt a
    WHERE a.id = attempt_id AND a.student_id = app.current_user_id()
  ));

CREATE POLICY attempt_answer_teacher_read ON public.attempt_answer
  FOR SELECT TO app_backend
  USING (EXISTS (
    SELECT 1
    FROM public.quiz_attempt a
    JOIN public.quiz q ON q.id = a.quiz_id
    WHERE a.id = attempt_id AND q.space_id IS NOT NULL AND app.owns_space(q.space_id)
  ));

-- ============================================================================
-- 5. LEARNER ANALYTICS — student owns; verified parent reads all subjects;
--    teacher reads only their scoped subject.
-- ============================================================================

CREATE POLICY mastery_owner ON public.mastery_estimate
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

CREATE POLICY mastery_guardian_read ON public.mastery_estimate
  FOR SELECT TO app_backend
  USING (app.is_verified_guardian_of(student_id) OR app.is_admin());

CREATE POLICY coverage_owner ON public.coverage_record
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

CREATE POLICY coverage_viewers_read ON public.coverage_record
  FOR SELECT TO app_backend
  USING (
    app.is_verified_guardian_of(student_id)
    OR app.teaches_student_subject(student_id, subject_id)
    OR app.is_admin()
  );

CREATE POLICY readiness_owner ON public.exam_readiness_score
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

CREATE POLICY readiness_viewers_read ON public.exam_readiness_score
  FOR SELECT TO app_backend
  USING (
    app.is_verified_guardian_of(student_id)
    OR app.teaches_student_subject(student_id, subject_id)
    OR app.is_admin()
  );

CREATE POLICY review_owner ON public.review_schedule
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

-- ============================================================================
-- 6. TUTOR SESSIONS — OWNER ONLY.
--    Deliberately no teacher/parent/admin read path: chat content is a minor's
--    private data (prd §4.2, §21 TEL-3). Admins get audit metadata, not content.
-- ============================================================================

CREATE POLICY chat_session_owner ON public.chat_session
  FOR ALL TO app_backend
  USING (student_id = app.current_user_id())
  WITH CHECK (student_id = app.current_user_id());

CREATE POLICY message_owner ON public.message
  FOR ALL TO app_backend
  USING (EXISTS (
    SELECT 1 FROM public.chat_session s
    WHERE s.id = session_id AND s.student_id = app.current_user_id()
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.chat_session s
    WHERE s.id = session_id AND s.student_id = app.current_user_id()
  ));

CREATE POLICY visual_aid_owner ON public.visual_aid
  FOR ALL TO app_backend
  USING (EXISTS (
    SELECT 1 FROM public.message m
    JOIN public.chat_session s ON s.id = m.session_id
    WHERE m.id = message_id AND s.student_id = app.current_user_id()
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.message m
    JOIN public.chat_session s ON s.id = m.session_id
    WHERE m.id = message_id AND s.student_id = app.current_user_id()
  ));

-- ============================================================================
-- 7. SECURITY & PLATFORM — admin read only; writes come from service jobs.
-- ============================================================================

CREATE POLICY component_admin_read ON public.agent_component
  FOR SELECT TO app_backend USING (app.is_admin());
CREATE POLICY manifest_admin_read ON public.permission_manifest
  FOR SELECT TO app_backend USING (app.is_admin());
CREATE POLICY sbom_admin_read ON public.agent_sbom_entry
  FOR SELECT TO app_backend USING (app.is_admin());
CREATE POLICY vetting_admin_read ON public.vetting_result
  FOR SELECT TO app_backend USING (app.is_admin());

-- Audit trail: append-only from the app, readable by admins. No UPDATE/DELETE
-- policy exists, so the trail cannot be tampered with via app_backend.
CREATE POLICY audit_insert ON public.audit_log
  FOR INSERT TO app_backend WITH CHECK (true);
CREATE POLICY audit_admin_read ON public.audit_log
  FOR SELECT TO app_backend USING (app.is_admin());

-- Operational request log: written on every call, read on the admin panel (TEL-5)
CREATE POLICY reqlog_insert ON public.api_request_log
  FOR INSERT TO app_backend WITH CHECK (true);
CREATE POLICY reqlog_admin_read ON public.api_request_log
  FOR SELECT TO app_backend USING (app.is_admin());

-- ============================================================================
-- End of RLS policies.
-- ============================================================================
