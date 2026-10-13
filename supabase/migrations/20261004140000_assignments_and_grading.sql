-- ============================================================================
-- EduBridge AI — assignments, submissions and grading (classroom Phase 4)
--
-- prd.md §15 CL-7, tdd.md §3.6. Three tables, and the rule that decides their
-- shape: all application users share ONE database role, so a column grant
-- cannot tell a teacher from a student. A teacher-owned field on a
-- student-owned row would therefore be writable by both — which is why the
-- grade is its own table (`submission_grade`) rather than a column on the
-- submission, and why neither table has ANY write grant: students write
-- through app.save_submission_draft / turn_in / unsubmit, teachers through
-- app.save_grade, each reading the actor from app.current_user_id().
--
--   assignment             owner content, like announcement: RLS-governed
--                          INSERT, UPDATE narrowed to six columns, scheduling
--                          by `publish_at` (members never see a future one),
--                          deleted only by app.delete_assignment.
--   assignment_submission  one per (assignment, student). `turned_in_at` is the
--                          only state; late / missing / graded are DERIVED
--                          (app/classroom/status.py), never stored.
--   submission_grade       the teacher's grade and private feedback; the
--                          student reads it only once `returned_at` is set.
--
-- Visibility rules, all enforced HERE rather than in the service:
--   * A teacher sees a student's work only while that student is an ACTIVE
--     member (app.my_taught_students) — leaving ends teacher visibility
--     (user story 7.1) — and only once it is TURNED IN: a draft is the
--     student's own until they hand it in.
--   * A student never sees a classmate's submission or grade, and sees their
--     own grade only after it is returned.
--   * Once any grade row exists the work is locked: "editable until graded".
--
-- Integrity that is declarative rather than checked:
--   * the chapter tag belongs to the classroom's subject — a composite foreign
--     key (chapter_id, subject_id) -> chapter (id, subject_id);
--   * a submission and a grade belong to the same classroom as their
--     assignment — composite keys (assignment_id, space_id).
--
-- Races (plan R3): every submission or grade write takes one advisory lock per
-- (assignment, student), so a grade saved while the student edits or turns in
-- cannot leave edited work behind a grade. app.save_grade also takes FOR SHARE
-- on the assignment row, so lowering `points` cannot interleave with a grade
-- above the new maximum (the service takes FOR UPDATE before checking).
--
-- Idempotent: IF NOT EXISTS tables and indexes, guarded constraints, every
-- policy dropped before it is created, CREATE OR REPLACE functions.
-- ============================================================================

-- ── 1. Composite-key targets ────────────────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_space_id_subject') THEN
    ALTER TABLE public.classroom_space ADD CONSTRAINT uq_space_id_subject UNIQUE (id, subject_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_chapter_id_subject') THEN
    ALTER TABLE public.chapter ADD CONSTRAINT uq_chapter_id_subject UNIQUE (id, subject_id);
  END IF;
END $$;

-- ── 2. Tables ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.assignment (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id     uuid        NOT NULL,
  -- Denormalised from the space so per-subject reports never join through it;
  -- the composite key below makes it impossible for the two to disagree.
  subject_id   uuid        NOT NULL,
  author_id    uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  title        text        NOT NULL,
  instructions text        NOT NULL DEFAULT '',
  due_at       timestamptz,
  points       smallint,
  chapter_id   uuid,
  publish_at   timestamptz NOT NULL DEFAULT now(),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_assignment_space_subject FOREIGN KEY (space_id, subject_id)
    REFERENCES public.classroom_space (id, subject_id) ON DELETE CASCADE,
  -- MATCH SIMPLE: a NULL chapter_id skips the check, so the tag is optional.
  CONSTRAINT fk_assignment_chapter_subject FOREIGN KEY (chapter_id, subject_id)
    REFERENCES public.chapter (id, subject_id) ON DELETE RESTRICT,
  CONSTRAINT uq_assignment_id_space UNIQUE (id, space_id),
  CONSTRAINT ck_assignment_title CHECK (char_length(btrim(title)) BETWEEN 1 AND 200),
  CONSTRAINT ck_assignment_instructions CHECK (char_length(instructions) <= 10000),
  CONSTRAINT ck_assignment_points CHECK (points IS NULL OR points BETWEEN 1 AND 1000),
  CONSTRAINT ck_assignment_due_after_publish CHECK (due_at IS NULL OR due_at > publish_at)
);
CREATE INDEX IF NOT EXISTS ix_assignment_feed    ON public.assignment (space_id, publish_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_assignment_due     ON public.assignment (due_at) WHERE due_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_assignment_subject ON public.assignment (subject_id, chapter_id);
CREATE INDEX IF NOT EXISTS ix_assignment_author  ON public.assignment (author_id);
DROP TRIGGER IF EXISTS trg_assignment_updated ON public.assignment;
CREATE TRIGGER trg_assignment_updated BEFORE UPDATE ON public.assignment
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS public.assignment_submission (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid        NOT NULL,
  space_id      uuid        NOT NULL,
  student_id    uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  body          text        NOT NULL DEFAULT '',
  link_url      text,
  turned_in_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_submission_assignment FOREIGN KEY (assignment_id, space_id)
    REFERENCES public.assignment (id, space_id) ON DELETE CASCADE,
  CONSTRAINT uq_submission_one_per_student UNIQUE (assignment_id, student_id),
  -- The target for submission files (classroom Phase 6).
  CONSTRAINT uq_submission_id_space_student UNIQUE (id, space_id, student_id),
  CONSTRAINT ck_submission_body CHECK (char_length(body) <= 20000),
  CONSTRAINT ck_submission_link CHECK (
    link_url IS NULL OR (link_url ~ '^https://[^[:space:]]+$' AND char_length(link_url) <= 2048))
);
CREATE INDEX IF NOT EXISTS ix_submission_student ON public.assignment_submission (student_id);
DROP TRIGGER IF EXISTS trg_submission_updated ON public.assignment_submission;
CREATE TRIGGER trg_submission_updated BEFORE UPDATE ON public.assignment_submission
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE IF NOT EXISTS public.submission_grade (
  assignment_id uuid         NOT NULL,
  space_id      uuid         NOT NULL,
  student_id    uuid         NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  grade         numeric(6,2),
  feedback      text         NOT NULL DEFAULT '',
  graded_by     uuid         NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  graded_at     timestamptz  NOT NULL DEFAULT now(),
  returned_at   timestamptz,
  updated_at    timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (assignment_id, student_id),
  CONSTRAINT fk_grade_assignment FOREIGN KEY (assignment_id, space_id)
    REFERENCES public.assignment (id, space_id) ON DELETE CASCADE,
  CONSTRAINT ck_grade_nonneg CHECK (grade IS NULL OR grade >= 0),
  CONSTRAINT ck_grade_feedback CHECK (char_length(feedback) <= 5000)
);
CREATE INDEX IF NOT EXISTS ix_grade_student   ON public.submission_grade (student_id);
CREATE INDEX IF NOT EXISTS ix_grade_graded_by ON public.submission_grade (graded_by);
DROP TRIGGER IF EXISTS trg_grade_updated ON public.submission_grade;
CREATE TRIGGER trg_grade_updated BEFORE UPDATE ON public.submission_grade
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

COMMENT ON COLUMN public.assignment_submission.turned_in_at IS
  'NULL = draft. Set to clock_timestamp() by app.turn_in_submission only. Late, missing and graded '
  'are derived from this, assignment.due_at and submission_grade.returned_at — never stored.';
COMMENT ON COLUMN public.submission_grade.returned_at IS
  'When the student may see the grade and feedback (grade_student_read_returned). Never cleared.';

-- ── 3. Grants ───────────────────────────────────────────────────────────────
-- Explicit, then narrowed: ALTER DEFAULT PRIVILEGES (20260801120100:38) has
-- already granted SELECT/INSERT/UPDATE/DELETE on each new table.
-- assignment INSERT stays table-level, held by `assignment_insert` (the
-- announcement pattern, 20261004130000).
REVOKE UPDATE, DELETE ON public.assignment FROM app_backend;
GRANT  SELECT, INSERT ON public.assignment TO app_backend;
GRANT  UPDATE (title, instructions, due_at, points, chapter_id, publish_at)
  ON public.assignment TO app_backend;
REVOKE INSERT, UPDATE, DELETE ON public.assignment_submission, public.submission_grade FROM app_backend;
GRANT  SELECT ON public.assignment_submission, public.submission_grade TO app_backend;

ALTER TABLE public.assignment            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignment            FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.assignment_submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignment_submission FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.submission_grade      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_grade      FORCE  ROW LEVEL SECURITY;

-- ── 4. Helpers ──────────────────────────────────────────────────────────────
-- Policy helper (R1, set form). (space, student) pairs of ACTIVE members of the
-- caller's spaces. "Leaving ends teacher visibility" (user story 7.1) IS this.
CREATE OR REPLACE FUNCTION app.my_taught_students()
RETURNS TABLE (space_id uuid, student_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT e.space_id, e.student_id
    FROM public.enrollment e
   WHERE e.left_at IS NULL
     AND e.space_id IN (SELECT app.my_owned_space_ids());
$$;

-- Policy helper (R6). True only for the owner, and only when no grade on the
-- assignment exceeds the proposed points (NULL points = ungraded, so any grade
-- conflicts). Anyone else gets false, so it is not an oracle.
CREATE OR REPLACE FUNCTION app.points_compatible(p_assignment uuid, p_points smallint)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((
    SELECT app.owns_space(a.space_id)
       AND NOT EXISTS (
             SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = a.id
                AND g.grade IS NOT NULL
                AND (p_points IS NULL OR g.grade > p_points))
      FROM public.assignment a
     WHERE a.id = p_assignment
  ), false);
$$;

-- INTERNAL (no grant, R9). The space the caller may submit to for this
-- assignment, or NULL: published, active classroom, active member, and past
-- the guardian gate — the Class 9–10 rule at the database too, not only on
-- the route.
CREATE OR REPLACE FUNCTION app.submittable_space(p_assignment uuid)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT a.space_id
    FROM public.assignment a
    JOIN public.classroom_space s
      ON s.id = a.space_id AND s.status = 'active'
    JOIN public.enrollment e
      ON e.space_id = a.space_id AND e.student_id = app.current_user_id() AND e.left_at IS NULL
   WHERE a.id = p_assignment
     AND a.publish_at <= now()
     AND app.caller_passes_guardian_gate();
$$;

-- INTERNAL (R3). One transaction-scoped lock per (assignment, student), shared
-- by every student and teacher write path.
CREATE OR REPLACE FUNCTION app.lock_submission(p_assignment uuid, p_student uuid)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT pg_advisory_xact_lock(hashtextextended(p_assignment::text || ':' || p_student::text, 0));
$$;

-- ── 5. Policies ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS assignment_owner_read  ON public.assignment;
DROP POLICY IF EXISTS assignment_member_read ON public.assignment;
DROP POLICY IF EXISTS assignment_insert      ON public.assignment;
DROP POLICY IF EXISTS assignment_update      ON public.assignment;

CREATE POLICY assignment_owner_read ON public.assignment
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin()));

-- Scheduling (owner decision 9): a future assignment is invisible to members
-- at the database — the same rule as announcement_member_read.
CREATE POLICY assignment_member_read ON public.assignment
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_member_space_ids()) AND publish_at <= now());

CREATE POLICY assignment_insert ON public.assignment
  FOR INSERT TO app_backend
  WITH CHECK (author_id = app.current_user_id() AND app.owns_active_space(space_id));

CREATE POLICY assignment_update ON public.assignment
  FOR UPDATE TO app_backend
  USING      (author_id = app.current_user_id() AND app.owns_active_space(space_id))
  WITH CHECK (author_id = app.current_user_id() AND app.owns_active_space(space_id)
              AND app.points_compatible(id, points));
-- No DELETE policy and no DELETE grant: deletion is app.delete_assignment,
-- which Phase 6 extends to collect stored file keys before the cascade.

DROP POLICY IF EXISTS submission_read_own     ON public.assignment_submission;
DROP POLICY IF EXISTS submission_teacher_read ON public.assignment_submission;

CREATE POLICY submission_read_own ON public.assignment_submission
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

CREATE POLICY submission_teacher_read ON public.assignment_submission
  FOR SELECT TO app_backend
  USING (turned_in_at IS NOT NULL
         AND (space_id, student_id) IN (SELECT t.space_id, t.student_id FROM app.my_taught_students() t));

DROP POLICY IF EXISTS grade_teacher_read          ON public.submission_grade;
DROP POLICY IF EXISTS grade_student_read_returned ON public.submission_grade;

CREATE POLICY grade_teacher_read ON public.submission_grade
  FOR SELECT TO app_backend
  USING ((space_id, student_id) IN (SELECT t.space_id, t.student_id FROM app.my_taught_students() t));

CREATE POLICY grade_student_read_returned ON public.submission_grade
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id() AND returned_at IS NOT NULL);

-- ── 6. Student write functions — the only submission writers ───────────────
-- Outcomes, never RAISE (a RAISE would surface as 500): see each COMMENT.
CREATE OR REPLACE FUNCTION app.save_submission_draft(p_assignment uuid, p_body text, p_link text)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user  uuid := app.current_user_id();
  v_space uuid := app.submittable_space(p_assignment);
BEGIN
  IF v_space IS NULL THEN RETURN 'forbidden'; END IF;
  PERFORM app.lock_submission(p_assignment, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = p_assignment AND g.student_id = v_user) THEN
    RETURN 'graded';
  END IF;
  INSERT INTO public.assignment_submission (assignment_id, space_id, student_id, body, link_url)
  VALUES (p_assignment, v_space, v_user, coalesce(p_body, ''), p_link)
  ON CONFLICT ON CONSTRAINT uq_submission_one_per_student DO UPDATE
     SET body = EXCLUDED.body, link_url = EXCLUDED.link_url
   WHERE public.assignment_submission.turned_in_at IS NULL;
  IF NOT FOUND THEN RETURN 'turned_in'; END IF;   -- unsubmit first
  RETURN 'saved';
END;
$$;

CREATE OR REPLACE FUNCTION app.turn_in_submission(p_assignment uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user  uuid := app.current_user_id();
  v_space uuid := app.submittable_space(p_assignment);
BEGIN
  IF v_space IS NULL THEN RETURN 'forbidden'; END IF;
  PERFORM app.lock_submission(p_assignment, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = p_assignment AND g.student_id = v_user) THEN
    RETURN 'graded';
  END IF;
  -- clock_timestamp(): the real moment, not the transaction start. Nobody else
  -- can write this column (no grant), so lateness cannot be forged.
  INSERT INTO public.assignment_submission (assignment_id, space_id, student_id, turned_in_at)
  VALUES (p_assignment, v_space, v_user, clock_timestamp())
  ON CONFLICT ON CONSTRAINT uq_submission_one_per_student DO UPDATE
     SET turned_in_at = clock_timestamp()
   WHERE public.assignment_submission.turned_in_at IS NULL;
  IF NOT FOUND THEN RETURN 'already_turned_in'; END IF;
  RETURN 'turned_in';
END;
$$;

CREATE OR REPLACE FUNCTION app.unsubmit_submission(p_assignment uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user uuid := app.current_user_id();
BEGIN
  IF app.submittable_space(p_assignment) IS NULL THEN RETURN 'forbidden'; END IF;
  PERFORM app.lock_submission(p_assignment, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = p_assignment AND g.student_id = v_user) THEN
    RETURN 'graded';
  END IF;
  UPDATE public.assignment_submission SET turned_in_at = NULL
   WHERE assignment_id = p_assignment AND student_id = v_user AND turned_in_at IS NOT NULL;
  IF NOT FOUND THEN RETURN 'not_turned_in'; END IF;
  RETURN 'unsubmitted';
END;
$$;

-- ── 7. Teacher write functions ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION app.save_grade(p_assignment uuid, p_student uuid, p_grade numeric,
                                          p_feedback text, p_return boolean)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_space  uuid;
  v_points smallint;
BEGIN
  -- FOR SHARE: a concurrent change to `points` (which locks this row) waits
  -- for this grade, and this grade waits for it — never interleaved.
  SELECT a.space_id, a.points INTO v_space, v_points
    FROM public.assignment a WHERE a.id = p_assignment
     FOR SHARE;
  IF NOT FOUND OR NOT app.owns_active_space(v_space) THEN RETURN 'forbidden'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.enrollment e
                  WHERE e.space_id = v_space AND e.student_id = p_student AND e.left_at IS NULL) THEN
    RETURN 'forbidden';
  END IF;
  IF p_grade IS NOT NULL AND (v_points IS NULL OR p_grade < 0 OR p_grade > v_points) THEN
    RETURN 'invalid_grade';
  END IF;
  PERFORM app.lock_submission(p_assignment, p_student);
  INSERT INTO public.submission_grade
         (assignment_id, space_id, student_id, grade, feedback, graded_by, graded_at, returned_at)
  VALUES (p_assignment, v_space, p_student, p_grade, coalesce(p_feedback, ''),
          app.current_user_id(), clock_timestamp(),
          CASE WHEN p_return THEN clock_timestamp() END)
  ON CONFLICT (assignment_id, student_id) DO UPDATE
     SET grade       = EXCLUDED.grade,
         feedback    = EXCLUDED.feedback,
         graded_by   = EXCLUDED.graded_by,
         graded_at   = EXCLUDED.graded_at,
         -- Once returned, always returned: a later edit is visible at once.
         returned_at = COALESCE(public.submission_grade.returned_at, EXCLUDED.returned_at);
  RETURN 'saved';
END;
$$;

-- Phase 6 replaces this body (same signature, so CREATE OR REPLACE keeps the
-- grant) to collect every stored file key before the cascade removes the rows.
CREATE OR REPLACE FUNCTION app.delete_assignment(p_assignment uuid)
RETURNS TABLE (deleted boolean, object_keys text[])
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_space uuid;
BEGIN
  SELECT a.space_id INTO v_space FROM public.assignment a WHERE a.id = p_assignment;
  IF NOT FOUND OR NOT app.owns_active_space(v_space) THEN
    RETURN QUERY SELECT false, '{}'::text[];
    RETURN;
  END IF;
  DELETE FROM public.assignment WHERE id = p_assignment;
  RETURN QUERY SELECT true, '{}'::text[];
END;
$$;

-- ── 8. Function grants (C5, R9) and comments ───────────────────────────────
REVOKE ALL ON FUNCTION app.my_taught_students()                                FROM PUBLIC;
REVOKE ALL ON FUNCTION app.points_compatible(uuid, smallint)                   FROM PUBLIC;
REVOKE ALL ON FUNCTION app.submittable_space(uuid)                             FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lock_submission(uuid, uuid)                         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.save_submission_draft(uuid, text, text)             FROM PUBLIC;
REVOKE ALL ON FUNCTION app.turn_in_submission(uuid)                            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.unsubmit_submission(uuid)                           FROM PUBLIC;
REVOKE ALL ON FUNCTION app.save_grade(uuid, uuid, numeric, text, boolean)      FROM PUBLIC;
REVOKE ALL ON FUNCTION app.delete_assignment(uuid)                             FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.my_taught_students()                             TO app_backend;  -- used by policies
GRANT EXECUTE ON FUNCTION app.points_compatible(uuid, smallint)                TO app_backend;  -- used by a policy
GRANT EXECUTE ON FUNCTION app.save_submission_draft(uuid, text, text)          TO app_backend;
GRANT EXECUTE ON FUNCTION app.turn_in_submission(uuid)                         TO app_backend;
GRANT EXECUTE ON FUNCTION app.unsubmit_submission(uuid)                        TO app_backend;
GRANT EXECUTE ON FUNCTION app.save_grade(uuid, uuid, numeric, text, boolean)   TO app_backend;
GRANT EXECUTE ON FUNCTION app.delete_assignment(uuid)                          TO app_backend;
-- app.submittable_space and app.lock_submission: deliberately NO grant. They
-- are called only from the definer functions above, which run as the owner.

COMMENT ON FUNCTION app.my_taught_students() IS
  'RLS read predicate, set form: (space, student) for ACTIVE members of spaces the caller owns '
  'with live scope. Used by submission_teacher_read and grade_teacher_read; leaving ends visibility.';
COMMENT ON FUNCTION app.points_compatible(uuid, smallint) IS
  'PATCH /api/assignments/{id} and the assignment_update policy: false if any grade exceeds the '
  'proposed points, or the caller does not own the classroom.';
COMMENT ON FUNCTION app.submittable_space(uuid) IS
  'INTERNAL — no grant. Space the caller may submit to: published, active classroom, active member, '
  'guardian gate passed.';
COMMENT ON FUNCTION app.lock_submission(uuid, uuid) IS
  'INTERNAL — no grant. Advisory transaction lock per (assignment, student).';
COMMENT ON FUNCTION app.save_submission_draft(uuid, text, text) IS
  'PUT /api/assignments/{id}/submission. Outcomes: saved | forbidden | graded | turned_in.';
COMMENT ON FUNCTION app.turn_in_submission(uuid) IS
  'POST /api/assignments/{id}/submission/turn-in. Outcomes: turned_in | already_turned_in | '
  'forbidden | graded. Stamps clock_timestamp().';
COMMENT ON FUNCTION app.unsubmit_submission(uuid) IS
  'POST /api/assignments/{id}/submission/unsubmit. Outcomes: unsubmitted | not_turned_in | '
  'forbidden | graded.';
COMMENT ON FUNCTION app.save_grade(uuid, uuid, numeric, text, boolean) IS
  'PUT /api/assignments/{id}/grades/{student_id}. Owner of an active classroom, active student only. '
  'Outcomes: saved | forbidden | invalid_grade. Returning is one-way.';
COMMENT ON FUNCTION app.delete_assignment(uuid) IS
  'DELETE /api/assignments/{id}. Owner of an active classroom. Returns the stored file keys to '
  'delete after commit (always empty until classroom Phase 6).';
