-- ============================================================================
-- EduBridge AI — classroom files (classroom Phase 6)
--
-- prd.md §15 CL-8, tdd.md §3.6. Teacher attachments on announcements and
-- assignments (`material_attachment`) and student files on a submission
-- (`submission_file`). The BYTES live in a private storage bucket that only the
-- backend reaches, with storage-only S3 keys (owner decision 8); these tables
-- hold the metadata and decide who may see each object.
--
-- Who may see a file is the same rule as the thing it is attached to:
--   * a teacher attachment — the owner always; a member once its post is live
--     (a scheduled worksheet must not leak through its attachment);
--   * a submission file — the student always; the teacher only while the
--     student is an ACTIVE member AND only once the work is TURNED IN (the draft
--     rule of 20261004140000, applied to files).
--
-- The object key is the authorization boundary for storage, so the database
-- holds it to its owner: `ck_material_key` requires `s/<space_id>/…` and
-- `ck_subfile_key` requires `u/<space_id>/<student_id>/…`. A forged key — one
-- naming another classroom or another student — is a CHECK violation, not a
-- service check. Rows are immutable: there is no UPDATE grant on either table.
--
-- Quotas (plan R2) are checked inside the writing functions under an advisory
-- lock per classroom, so two parallel uploads cannot both pass a limit:
-- 5 files and 20 MiB per submission, 10 files per teacher post, 2 GiB per
-- classroom. The per-file cap is the application's (MAX_UPLOAD_BYTES, 5 MiB);
-- `ck_*_size` is a 9 MiB ceiling under the Next.js proxy's silent 10 MB
-- truncation, so a misconfigured server cannot store a truncated file.
--
-- Idempotent: IF NOT EXISTS tables and indexes, guarded constraints, policies
-- dropped before they are created, CREATE OR REPLACE functions, ON CONFLICT
-- bucket insert.
-- ============================================================================

-- ── 1. Composite-key target ─────────────────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_announcement_id_space') THEN
    ALTER TABLE public.announcement ADD CONSTRAINT uq_announcement_id_space UNIQUE (id, space_id);
  END IF;
END $$;

-- ── 2. Tables ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.material_attachment (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id        uuid        NOT NULL,
  announcement_id uuid,
  assignment_id   uuid,
  uploaded_by     uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  object_key      text        NOT NULL UNIQUE,
  filename        text        NOT NULL,
  content_type    text        NOT NULL,
  size_bytes      integer     NOT NULL,
  sha256          text        NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_material_announcement FOREIGN KEY (announcement_id, space_id)
    REFERENCES public.announcement (id, space_id) ON DELETE CASCADE,
  CONSTRAINT fk_material_assignment FOREIGN KEY (assignment_id, space_id)
    REFERENCES public.assignment (id, space_id) ON DELETE CASCADE,
  CONSTRAINT ck_material_one_parent CHECK (num_nonnulls(announcement_id, assignment_id) = 1),
  CONSTRAINT ck_material_key CHECK (
    object_key ~ '^s/[0-9a-f-]{36}/[0-9a-f]{32}$'
    AND left(object_key, 39) = 's/' || space_id::text || '/'),
  CONSTRAINT ck_material_type CHECK (content_type IN (
    'application/pdf', 'image/png', 'image/jpeg',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation')),
  CONSTRAINT ck_material_size CHECK (size_bytes BETWEEN 1 AND 9437184),
  CONSTRAINT ck_material_filename CHECK (char_length(filename) BETWEEN 1 AND 255),
  CONSTRAINT ck_material_sha CHECK (sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS ix_material_announcement ON public.material_attachment (announcement_id);
CREATE INDEX IF NOT EXISTS ix_material_assignment   ON public.material_attachment (assignment_id);
CREATE INDEX IF NOT EXISTS ix_material_space        ON public.material_attachment (space_id);
CREATE INDEX IF NOT EXISTS ix_material_uploaded_by  ON public.material_attachment (uploaded_by);

CREATE TABLE IF NOT EXISTS public.submission_file (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid        NOT NULL,
  space_id      uuid        NOT NULL,
  student_id    uuid        NOT NULL,
  object_key    text        NOT NULL UNIQUE,
  filename      text        NOT NULL,
  content_type  text        NOT NULL,
  size_bytes    integer     NOT NULL,
  sha256        text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  -- uq_submission_id_space_student (20261004140000) is the target, so a file
  -- can only ever belong to a submission in its own classroom, by its own student.
  CONSTRAINT fk_subfile_submission FOREIGN KEY (submission_id, space_id, student_id)
    REFERENCES public.assignment_submission (id, space_id, student_id) ON DELETE CASCADE,
  CONSTRAINT ck_subfile_key CHECK (
    object_key ~ '^u/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f]{32}$'
    AND left(object_key, 76) = 'u/' || space_id::text || '/' || student_id::text || '/'),
  CONSTRAINT ck_subfile_type CHECK (content_type IN (
    'application/pdf', 'image/png', 'image/jpeg',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation')),
  CONSTRAINT ck_subfile_size CHECK (size_bytes BETWEEN 1 AND 9437184),
  CONSTRAINT ck_subfile_filename CHECK (char_length(filename) BETWEEN 1 AND 255),
  CONSTRAINT ck_subfile_sha CHECK (sha256 ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS ix_subfile_submission ON public.submission_file (submission_id);
CREATE INDEX IF NOT EXISTS ix_subfile_space      ON public.submission_file (space_id);
CREATE INDEX IF NOT EXISTS ix_subfile_student    ON public.submission_file (student_id);

-- ── 3. Grants ───────────────────────────────────────────────────────────────
-- ALTER DEFAULT PRIVILEGES (20260801120100:38) granted everything; narrow it.
-- The owner may DELETE a teacher attachment (RETURNING its key, under RLS);
-- every other write is a function.
REVOKE INSERT, UPDATE, DELETE ON public.material_attachment, public.submission_file FROM app_backend;
GRANT  SELECT ON public.material_attachment, public.submission_file TO app_backend;
GRANT  DELETE ON public.material_attachment TO app_backend;

ALTER TABLE public.material_attachment ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.material_attachment FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.submission_file     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_file     FORCE  ROW LEVEL SECURITY;

-- ── 4. Helpers ──────────────────────────────────────────────────────────────
-- Policy helper: the attachment's parent post is live. Members see a teacher
-- file only from then — the same moment they see the post itself.
CREATE OR REPLACE FUNCTION app.material_parent_published(p_announcement uuid, p_assignment uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE(
    (SELECT n.publish_at <= now() FROM public.announcement n WHERE n.id = p_announcement),
    (SELECT a.publish_at <= now() FROM public.assignment a WHERE a.id = p_assignment),
    false);
$$;

-- INTERNAL (no grant): bytes stored for one classroom, for the 2 GiB quota.
CREATE OR REPLACE FUNCTION app.space_storage_bytes(p_space uuid)
RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((SELECT sum(size_bytes) FROM public.material_attachment WHERE space_id = p_space), 0)
       + COALESCE((SELECT sum(size_bytes) FROM public.submission_file     WHERE space_id = p_space), 0);
$$;

-- INTERNAL (no grant): one transaction-scoped lock per classroom's files, so
-- the quota checks below cannot be raced by parallel uploads. Held for the
-- length of an INSERT, never across an upload: the object is stored first.
CREATE OR REPLACE FUNCTION app.lock_space_files(p_space uuid)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT pg_advisory_xact_lock(hashtextextended('space-files:' || p_space::text, 0));
$$;

-- ── 5. Policies ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS material_owner_read   ON public.material_attachment;
DROP POLICY IF EXISTS material_member_read  ON public.material_attachment;
DROP POLICY IF EXISTS material_owner_delete ON public.material_attachment;

CREATE POLICY material_owner_read ON public.material_attachment
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin()));

CREATE POLICY material_member_read ON public.material_attachment
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_member_space_ids())
         AND app.material_parent_published(announcement_id, assignment_id));

CREATE POLICY material_owner_delete ON public.material_attachment
  FOR DELETE TO app_backend
  USING (app.owns_active_space(space_id));

DROP POLICY IF EXISTS subfile_read_own     ON public.submission_file;
DROP POLICY IF EXISTS subfile_teacher_read ON public.submission_file;

CREATE POLICY subfile_read_own ON public.submission_file
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

-- Explicit about BOTH conditions rather than leaning on the submission's own
-- policy through a subquery, so a later change to `submission_teacher_read`
-- cannot widen this one by accident (the B18 lesson).
CREATE POLICY subfile_teacher_read ON public.submission_file
  FOR SELECT TO app_backend
  USING ((space_id, student_id) IN (SELECT t.space_id, t.student_id FROM app.my_taught_students() t)
         AND EXISTS (SELECT 1 FROM public.assignment_submission s
                      WHERE s.id = submission_id AND s.turned_in_at IS NOT NULL));

-- ── 6. Writing functions ────────────────────────────────────────────────────
-- POST /api/assignments/{id}/submission/files. The caller has ALREADY stored
-- the object under p_object_key; on any outcome but 'added' it deletes it.
CREATE OR REPLACE FUNCTION app.add_submission_file(
  p_assignment uuid, p_object_key text, p_filename text, p_content_type text,
  p_size integer, p_sha256 text)
RETURNS TABLE (outcome text, new_file_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_user  uuid := app.current_user_id();
  v_space uuid := app.submittable_space(p_assignment);
  v_sub   uuid;
  v_count integer;
  v_bytes bigint;
  v_id    uuid;
BEGIN
  IF v_space IS NULL THEN RETURN QUERY SELECT 'forbidden', NULL::uuid; RETURN; END IF;
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

  PERFORM app.lock_space_files(v_space);
  SELECT count(*), COALESCE(sum(f.size_bytes), 0) INTO v_count, v_bytes
    FROM public.submission_file f WHERE f.submission_id = v_sub;
  IF v_count >= 5 THEN RETURN QUERY SELECT 'too_many_files', NULL::uuid; RETURN; END IF;
  IF v_bytes + p_size > 20971520 THEN
    RETURN QUERY SELECT 'submission_quota', NULL::uuid; RETURN;
  END IF;
  IF app.space_storage_bytes(v_space) + p_size > 2147483648 THEN
    RETURN QUERY SELECT 'classroom_quota', NULL::uuid; RETURN;
  END IF;

  -- ck_subfile_key refuses a key outside u/<this space>/<this student>/.
  INSERT INTO public.submission_file
         (submission_id, space_id, student_id, object_key, filename, content_type, size_bytes, sha256)
  VALUES (v_sub, v_space, v_user, p_object_key, p_filename, p_content_type, p_size, p_sha256)
  RETURNING id INTO v_id;
  RETURN QUERY SELECT 'added', v_id;
END;
$$;

-- DELETE /api/submission-files/{id}. Returns the key for after-commit deletion.
CREATE OR REPLACE FUNCTION app.remove_submission_file(p_file uuid)
RETURNS TABLE (outcome text, removed_object_key text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_user uuid := app.current_user_id();
  v_row  record;
BEGIN
  SELECT f.object_key, s.assignment_id, s.turned_in_at INTO v_row
    FROM public.submission_file f
    JOIN public.assignment_submission s ON s.id = f.submission_id
   WHERE f.id = p_file AND f.student_id = v_user;
  IF NOT FOUND OR app.submittable_space(v_row.assignment_id) IS NULL THEN
    RETURN QUERY SELECT 'forbidden', NULL::text; RETURN;
  END IF;
  PERFORM app.lock_submission(v_row.assignment_id, v_user);
  IF EXISTS (SELECT 1 FROM public.submission_grade g
              WHERE g.assignment_id = v_row.assignment_id AND g.student_id = v_user) THEN
    RETURN QUERY SELECT 'graded', NULL::text; RETURN;
  END IF;
  IF v_row.turned_in_at IS NOT NULL THEN RETURN QUERY SELECT 'turned_in', NULL::text; RETURN; END IF;
  DELETE FROM public.submission_file WHERE id = p_file;
  RETURN QUERY SELECT 'removed', v_row.object_key;
END;
$$;

-- POST /api/announcements/{id}/attachments and /api/assignments/{id}/attachments.
-- Exactly one parent. The caller has already stored the object.
CREATE OR REPLACE FUNCTION app.add_material_attachment(
  p_announcement uuid, p_assignment uuid, p_object_key text, p_filename text,
  p_content_type text, p_size integer, p_sha256 text)
RETURNS TABLE (outcome text, new_file_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_space uuid;
  v_count integer;
  v_id    uuid;
BEGIN
  IF num_nonnulls(p_announcement, p_assignment) <> 1 THEN
    RETURN QUERY SELECT 'forbidden', NULL::uuid; RETURN;
  END IF;
  IF p_announcement IS NOT NULL THEN
    SELECT n.space_id INTO v_space FROM public.announcement n WHERE n.id = p_announcement;
  ELSE
    SELECT a.space_id INTO v_space FROM public.assignment a WHERE a.id = p_assignment;
  END IF;
  IF v_space IS NULL OR NOT app.owns_active_space(v_space) THEN
    RETURN QUERY SELECT 'forbidden', NULL::uuid; RETURN;
  END IF;

  PERFORM app.lock_space_files(v_space);
  SELECT count(*) INTO v_count FROM public.material_attachment m
   WHERE m.announcement_id IS NOT DISTINCT FROM p_announcement
     AND m.assignment_id   IS NOT DISTINCT FROM p_assignment;
  IF v_count >= 10 THEN RETURN QUERY SELECT 'too_many_files', NULL::uuid; RETURN; END IF;
  IF app.space_storage_bytes(v_space) + p_size > 2147483648 THEN
    RETURN QUERY SELECT 'classroom_quota', NULL::uuid; RETURN;
  END IF;

  -- ck_material_key refuses a key outside s/<this space>/.
  INSERT INTO public.material_attachment
         (space_id, announcement_id, assignment_id, uploaded_by,
          object_key, filename, content_type, size_bytes, sha256)
  VALUES (v_space, p_announcement, p_assignment, app.current_user_id(),
          p_object_key, p_filename, p_content_type, p_size, p_sha256)
  RETURNING id INTO v_id;
  RETURN QUERY SELECT 'added', v_id;
END;
$$;

-- DELETE /api/assignments/{id} — the Phase 4 body, now collecting EVERY stored
-- key before the cascade removes the rows: teacher attachments, and every
-- student's files, including drafts and students who have LEFT, none of which
-- the teacher can see under RLS. SAME SIGNATURE, so CREATE OR REPLACE keeps the
-- grant and comment.
CREATE OR REPLACE FUNCTION app.delete_assignment(p_assignment uuid)
RETURNS TABLE (deleted boolean, object_keys text[])
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_space uuid;
  v_keys  text[];
BEGIN
  SELECT a.space_id INTO v_space FROM public.assignment a WHERE a.id = p_assignment;
  IF NOT FOUND OR NOT app.owns_active_space(v_space) THEN
    RETURN QUERY SELECT false, '{}'::text[];
    RETURN;
  END IF;
  SELECT COALESCE(array_agg(k.key), '{}') INTO v_keys FROM (
    SELECT m.object_key AS key FROM public.material_attachment m WHERE m.assignment_id = p_assignment
    UNION ALL
    SELECT f.object_key FROM public.submission_file f
      JOIN public.assignment_submission s ON s.id = f.submission_id
     WHERE s.assignment_id = p_assignment
  ) k;
  DELETE FROM public.assignment WHERE id = p_assignment;
  RETURN QUERY SELECT true, v_keys;
END;
$$;

-- ── 7. Function grants and comments ─────────────────────────────────────────
REVOKE ALL ON FUNCTION app.material_parent_published(uuid, uuid)                       FROM PUBLIC;
REVOKE ALL ON FUNCTION app.space_storage_bytes(uuid)                                   FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lock_space_files(uuid)                                      FROM PUBLIC;
REVOKE ALL ON FUNCTION app.add_submission_file(uuid, text, text, text, integer, text)  FROM PUBLIC;
REVOKE ALL ON FUNCTION app.remove_submission_file(uuid)                                FROM PUBLIC;
REVOKE ALL ON FUNCTION app.add_material_attachment(uuid, uuid, text, text, text, integer, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.material_parent_published(uuid, uuid)                    TO app_backend;  -- used by a policy
GRANT EXECUTE ON FUNCTION app.add_submission_file(uuid, text, text, text, integer, text) TO app_backend;
GRANT EXECUTE ON FUNCTION app.remove_submission_file(uuid)                             TO app_backend;
GRANT EXECUTE ON FUNCTION app.add_material_attachment(uuid, uuid, text, text, text, integer, text) TO app_backend;
-- app.space_storage_bytes and app.lock_space_files: deliberately NO grant (R9).

COMMENT ON FUNCTION app.material_parent_published(uuid, uuid) IS
  'RLS helper (material_member_read): the attachment''s announcement or assignment is live.';
COMMENT ON FUNCTION app.space_storage_bytes(uuid) IS
  'INTERNAL — no grant. Bytes stored for one classroom (2 GiB quota).';
COMMENT ON FUNCTION app.lock_space_files(uuid) IS
  'INTERNAL — no grant. Advisory transaction lock per classroom for the file quotas.';
COMMENT ON FUNCTION app.add_submission_file(uuid, text, text, text, integer, text) IS
  'POST /api/assignments/{id}/submission/files. Outcomes: added | forbidden | graded | turned_in | '
  'too_many_files | submission_quota | classroom_quota. The key must be u/<space>/<caller>/<hex32>.';
COMMENT ON FUNCTION app.remove_submission_file(uuid) IS
  'DELETE /api/submission-files/{id}. Outcomes: removed | forbidden | graded | turned_in. '
  'Returns the object key to delete after commit.';
COMMENT ON FUNCTION app.add_material_attachment(uuid, uuid, text, text, text, integer, text) IS
  'POST /api/announcements/{id}/attachments, POST /api/assignments/{id}/attachments. Owner of an '
  'active classroom. Outcomes: added | forbidden | too_many_files | classroom_quota.';
COMMENT ON FUNCTION app.delete_assignment(uuid) IS
  'DELETE /api/assignments/{id}. Owner of an active classroom. Returns every stored file key '
  '(teacher attachments and all student files) to delete after commit.';

-- ── 8. The private bucket ───────────────────────────────────────────────────
-- Created here so it is not a hand-applied step that exists in one environment
-- and no migration (finding F1's lesson). Private, with the same type and size
-- limits as the tables. NO storage.objects policy is created: users are not
-- Supabase Auth users, and only the backend — holding storage-only S3 keys —
-- touches objects. Skipped where there is no `storage` schema (a plain
-- PostgreSQL shadow database).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    BEGIN
      INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
      VALUES ('classroom-files', 'classroom-files', false, 9437184,
              ARRAY['application/pdf', 'image/png', 'image/jpeg',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    'application/vnd.openxmlformats-officedocument.presentationml.presentation'])
      ON CONFLICT (id) DO NOTHING;
    EXCEPTION WHEN insufficient_privilege THEN
      RAISE WARNING 'classroom-files bucket NOT created (insufficient privilege): create it in the '
                    'Supabase dashboard — private, 9 MB limit, PDF/PNG/JPEG/DOCX/PPTX.';
    END;
  END IF;
END $$;
