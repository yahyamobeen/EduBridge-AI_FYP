-- ============================================================================
-- EduBridge AI — several links on a piece of work (classroom Phase 6b)
--
-- prd.md §15 CL-7 (amended 2026-10-05), tdd.md §3.6. A student's work may carry
-- up to five https links, "like Google Classroom" (owner decision 2026-10-05),
-- each its own row — added and removed one at a time beside the files.
--
-- Who may see a link is the rule for a submission file (20261004150000): the
-- student always; the teacher only while the student is an ACTIVE member AND
-- only once the work is TURNED IN. Both conditions are stated in
-- `link_teacher_read` itself, not inherited through a subquery (the B18 lesson).
-- No classmate path exists.
--
-- `assignment_submission.link_url` (20261004140000) is SUPERSEDED: its values
-- are copied here and the column is cleared. It stays, unread — dropping it
-- would mean replacing app.save_submission_draft, which still takes p_link;
-- the service now always passes NULL (the student_profile.language_pref
-- precedent, 20260816200000).
--
-- Idempotent: IF NOT EXISTS table and indexes, policies dropped before they are
-- created, CREATE OR REPLACE functions, ON CONFLICT copy.
-- ============================================================================

-- ── 1. Table ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.submission_link (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid        NOT NULL,
  space_id      uuid        NOT NULL,
  student_id    uuid        NOT NULL,
  url           text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  -- uq_submission_id_space_student (20261004140000) is the target, so a link
  -- can only ever belong to a submission in its own classroom, by its own student.
  CONSTRAINT fk_sublink_submission FOREIGN KEY (submission_id, space_id, student_id)
    REFERENCES public.assignment_submission (id, space_id, student_id) ON DELETE CASCADE,
  -- The same rule as ck_submission_link: https and nothing else, never
  -- `javascript:`; the client renders it with rel="noopener noreferrer".
  CONSTRAINT ck_sublink_url CHECK (url ~ '^https://[^[:space:]]+$' AND char_length(url) <= 2048),
  -- Adding the same link twice is not a second link.
  CONSTRAINT uq_sublink_url UNIQUE (submission_id, url)
);
-- submission_id is the leading column of uq_sublink_url's index.
CREATE INDEX IF NOT EXISTS ix_sublink_space   ON public.submission_link (space_id);
CREATE INDEX IF NOT EXISTS ix_sublink_student ON public.submission_link (student_id);

-- ── 2. Grants ───────────────────────────────────────────────────────────────
-- ALTER DEFAULT PRIVILEGES (20260801120100:38) granted everything; narrow it.
-- Every write is a function.
REVOKE INSERT, UPDATE, DELETE ON public.submission_link FROM app_backend;
GRANT  SELECT ON public.submission_link TO app_backend;

ALTER TABLE public.submission_link ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_link FORCE  ROW LEVEL SECURITY;

-- ── 3. Policies ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS link_read_own     ON public.submission_link;
DROP POLICY IF EXISTS link_teacher_read ON public.submission_link;

CREATE POLICY link_read_own ON public.submission_link
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

CREATE POLICY link_teacher_read ON public.submission_link
  FOR SELECT TO app_backend
  USING ((space_id, student_id) IN (SELECT t.space_id, t.student_id FROM app.my_taught_students() t)
         AND EXISTS (SELECT 1 FROM public.assignment_submission s
                      WHERE s.id = submission_id AND s.turned_in_at IS NOT NULL));

-- ── 4. Writing functions ────────────────────────────────────────────────────
-- POST /api/assignments/{id}/submission/links. The gate, the lock and the
-- graded/turned-in refusals are app.add_submission_file's; the cap is 5 links.
CREATE OR REPLACE FUNCTION app.add_submission_link(p_assignment uuid, p_url text)
RETURNS TABLE (outcome text, new_link_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_user  uuid := app.current_user_id();
  v_space uuid := app.submittable_space(p_assignment);
  v_sub   uuid;
  v_id    uuid;
BEGIN
  IF v_space IS NULL THEN RETURN QUERY SELECT 'forbidden', NULL::uuid; RETURN; END IF;
  -- Checked here, not left to ck_sublink_url: a CHECK violation would be a 500.
  IF p_url IS NULL OR p_url !~ '^https://[^[:space:]]+$' OR char_length(p_url) > 2048 THEN
    RETURN QUERY SELECT 'invalid_url', NULL::uuid; RETURN;
  END IF;
  PERFORM app.lock_submission(p_assignment, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = p_assignment AND g.student_id = v_user) THEN
    RETURN QUERY SELECT 'graded', NULL::uuid; RETURN;
  END IF;
  INSERT INTO public.assignment_submission (assignment_id, space_id, student_id)
  VALUES (p_assignment, v_space, v_user)
  ON CONFLICT ON CONSTRAINT uq_submission_one_per_student DO NOTHING;
  SELECT s.id INTO v_sub FROM public.assignment_submission s
   WHERE s.assignment_id = p_assignment AND s.student_id = v_user AND s.turned_in_at IS NULL;
  IF NOT FOUND THEN RETURN QUERY SELECT 'turned_in', NULL::uuid; RETURN; END IF;

  -- The same link again is the link already there: not an error, not a second row.
  SELECT l.id INTO v_id FROM public.submission_link l
   WHERE l.submission_id = v_sub AND l.url = p_url;
  IF FOUND THEN RETURN QUERY SELECT 'added', v_id; RETURN; END IF;

  IF (SELECT count(*) FROM public.submission_link l WHERE l.submission_id = v_sub) >= 5 THEN
    RETURN QUERY SELECT 'too_many_links', NULL::uuid; RETURN;
  END IF;

  -- clock_timestamp(), as turn-in does: links list in the order they were
  -- added, even several within one transaction.
  INSERT INTO public.submission_link (submission_id, space_id, student_id, url, created_at)
  VALUES (v_sub, v_space, v_user, p_url, clock_timestamp())
  RETURNING id INTO v_id;
  RETURN QUERY SELECT 'added', v_id;
END;
$$;

-- DELETE /api/submission-links/{id}. The caller's own link, while the work is
-- an ungraded draft.
CREATE OR REPLACE FUNCTION app.remove_submission_link(p_link uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user uuid := app.current_user_id();
  v_row  record;
BEGIN
  SELECT s.assignment_id, s.turned_in_at INTO v_row
    FROM public.submission_link l
    JOIN public.assignment_submission s ON s.id = l.submission_id
   WHERE l.id = p_link AND l.student_id = v_user;
  IF NOT FOUND OR app.submittable_space(v_row.assignment_id) IS NULL THEN
    RETURN 'forbidden';
  END IF;
  PERFORM app.lock_submission(v_row.assignment_id, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = v_row.assignment_id AND g.student_id = v_user) THEN
    RETURN 'graded';
  END IF;
  IF v_row.turned_in_at IS NOT NULL THEN RETURN 'turned_in'; END IF;
  DELETE FROM public.submission_link WHERE id = p_link;
  RETURN 'removed';
END;
$$;

REVOKE ALL ON FUNCTION app.add_submission_link(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.remove_submission_link(uuid)    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.add_submission_link(uuid, text) TO app_backend;
GRANT EXECUTE ON FUNCTION app.remove_submission_link(uuid)    TO app_backend;

COMMENT ON FUNCTION app.add_submission_link(uuid, text) IS
  'POST /api/assignments/{id}/submission/links. Outcomes: added | forbidden | invalid_url | graded | '
  'turned_in | too_many_links (5). Adding a link already there returns it.';
COMMENT ON FUNCTION app.remove_submission_link(uuid) IS
  'DELETE /api/submission-links/{id}. Outcomes: removed | forbidden | graded | turned_in.';

-- ── 5. The single link moves into the table ─────────────────────────────────
-- Under the migration role, which bypasses RLS (as 20260817120000's UPDATE of
-- auth_token did). Copied first, then cleared, so a re-run copies nothing.
INSERT INTO public.submission_link (submission_id, space_id, student_id, url, created_at)
SELECT s.id, s.space_id, s.student_id, s.link_url, s.updated_at
  FROM public.assignment_submission s
 WHERE s.link_url IS NOT NULL
ON CONFLICT ON CONSTRAINT uq_sublink_url DO NOTHING;

UPDATE public.assignment_submission SET link_url = NULL WHERE link_url IS NOT NULL;

COMMENT ON COLUMN public.assignment_submission.link_url IS
  'SUPERSEDED by submission_link (20261005120000) and always NULL: kept only because '
  'app.save_submission_draft still takes p_link. Read nothing from it.';
