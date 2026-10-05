-- ============================================================================
-- EduBridge AI — the parent's read-only classroom overview (classroom Phase 8)
--
-- prd.md §15 CL-10, tdd.md §3.6: a parent with a VERIFIED guardian link sees
-- their child's classrooms, teachers, assignments, deadlines, turn-in state and
-- RETURNED grades — never private feedback, submission content, files, links,
-- the chat, or classmates.
--
-- A FUNCTION, NOT PARENT POLICIES. Row-Level Security is per ROW: a parent
-- policy on assignment_submission or submission_grade would hand over the
-- whole row — the body, the feedback — and the application would be the only
-- thing standing between a parent and a teacher's private note. This function
-- returns exactly the columns CL-10 allows, and the tables gain no parent read
-- path at all (test_classroom_rls.py asserts a parent reads none of them).
--
-- NO PARAMETERS. The parent is app.current_user_id() — the change_password
-- pattern (20260816210000) — so it cannot be aimed at another family's child.
--
-- Every verified child is listed, even one in no classroom (a row with NULL
-- classroom columns), so a parent sees "not in a classroom yet", not nothing.
-- A classroom the child LEFT drops out. An archived classroom stays, with its
-- status, so returned grades remain visible. Assignments: published ones only,
-- due within the last 120 days or with no due date.
--
-- Idempotent: CREATE OR REPLACE (a new signature).
-- ============================================================================

-- GET /api/parent/classrooms
CREATE OR REPLACE FUNCTION app.guardian_classroom_overview()
RETURNS TABLE (student_id uuid, student_name text,
               space_id uuid, space_title text, space_status space_status,
               subject_name text, teacher_name text,
               assignment_id uuid, assignment_title text, due_at timestamptz,
               points smallint, turned_in_at timestamptz,
               grade numeric, returned_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT st.id, st.full_name,
         s.id, s.title, s.status, sub.name, t.full_name,
         a.id, a.title, a.due_at, a.points, sm.turned_in_at,
         -- A grade is the student's from the moment it is returned, and not
         -- before: an unreturned grade is still the teacher's draft.
         CASE WHEN g.returned_at IS NOT NULL THEN g.grade END,
         g.returned_at
    FROM public.app_user p
    JOIN public.guardian_link gl
      ON gl.parent_id = p.id AND gl.status = 'verified'
    JOIN public.app_user st
      ON st.id = gl.student_id AND st.role = 'student'
     AND st.status = 'active' AND st.deleted_at IS NULL
    LEFT JOIN (public.enrollment e
               JOIN public.classroom_space s ON s.id = e.space_id
               JOIN public.subject sub       ON sub.id = s.subject_id
               JOIN public.app_user t        ON t.id = s.owner_id)
      ON e.student_id = st.id AND e.left_at IS NULL
    LEFT JOIN public.assignment a
      ON a.space_id = s.id
     AND a.publish_at <= now()
     AND (a.due_at IS NULL OR a.due_at > now() - interval '120 days')
    LEFT JOIN public.assignment_submission sm
      ON sm.assignment_id = a.id AND sm.student_id = st.id
    LEFT JOIN public.submission_grade g
      ON g.assignment_id = a.id AND g.student_id = st.id
   WHERE p.id = app.current_user_id()
     AND p.role = 'parent'
     AND p.status = 'active'
     AND p.deleted_at IS NULL;
$$;

REVOKE ALL ON FUNCTION app.guardian_classroom_overview() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.guardian_classroom_overview() TO app_backend;

COMMENT ON FUNCTION app.guardian_classroom_overview() IS
  'GET /api/parent/classrooms. Anchored on the caller (no parameters): a parent''s verified '
  'children, their current classrooms (archived included), published assignments due in the '
  'last 120 days or undated, turn-in time, and grades once returned. Never feedback, work, '
  'files, links, chat or classmates.';
