-- ============================================================================
-- EduBridge AI — announcement ownership and scheduling (classroom Phase 3)
--
-- Two things, both enforced by the DATABASE rather than the service:
--
--   1. Authorship. `announcement_write` (20260801120100:302-304) checked only
--      app.owns_space(space_id) — never that author_id was the caller — so an
--      owner could post as anyone, and there was no UPDATE or DELETE policy at
--      all. Insert, update and delete now each require
--        author_id = app.current_user_id() AND app.owns_active_space(space_id)
--      and an archived classroom is read-only for its owner too.
--
--   2. Scheduling (prd.md §15 CL-5, owner decision 9, 2026-10-03). A post with a
--      future `publish_at` is invisible to members AT THE DATABASE: the member
--      read policy adds `publish_at <= now()`. No job publishes it — it simply
--      becomes visible when the time passes. The owner sees it all along.
--
-- Reads use the set-returning helpers from 20261004120000, so the policy runs
-- once per query, not once per row.
--
-- UPDATE is narrowed to (body, publish_at): `author_id`, `space_id` and
-- `created_at` cannot be rewritten. INSERT and DELETE stay table-level and are
-- governed by the policies below.
--
-- DRY-RUN PRE-CHECK: `SELECT count(*) FROM announcement` — rows violating the
-- new body CHECK would fail it; nothing has written this table yet.
--
-- Idempotent: guarded constraint, IF NOT EXISTS columns and indexes, every
-- policy dropped before it is created.
-- ============================================================================

ALTER TABLE public.announcement ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.announcement ADD COLUMN IF NOT EXISTS publish_at timestamptz NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_announcement_updated ON public.announcement;
CREATE TRIGGER trg_announcement_updated BEFORE UPDATE ON public.announcement
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_announcement_body') THEN
    ALTER TABLE public.announcement
      ADD CONSTRAINT ck_announcement_body CHECK (char_length(btrim(body)) BETWEEN 1 AND 5000);
  END IF;
END $$;

-- The stream is ordered by publish time (a scheduled post appears in its slot
-- when it goes live), keyset-paginated on (publish_at, id).
-- BEFORE (20260801120000:371): ix_announcement_space (space_id, created_at DESC)
DROP INDEX IF EXISTS public.ix_announcement_space;
CREATE INDEX IF NOT EXISTS ix_announcement_feed
  ON public.announcement (space_id, publish_at DESC, id DESC);
-- author_id is ON DELETE RESTRICT; an index keeps that check off a full scan.
CREATE INDEX IF NOT EXISTS ix_announcement_author ON public.announcement (author_id);

-- BEFORE (20260801120100:298-304):
--   announcement_read  FOR SELECT USING (app.is_enrolled_in(space_id)
--                                        OR app.owns_space(space_id) OR app.is_admin())
--   announcement_write FOR INSERT WITH CHECK (app.owns_space(space_id))   -- author never checked
DROP POLICY IF EXISTS announcement_read        ON public.announcement;
DROP POLICY IF EXISTS announcement_write       ON public.announcement;
DROP POLICY IF EXISTS announcement_owner_read  ON public.announcement;
DROP POLICY IF EXISTS announcement_member_read ON public.announcement;
DROP POLICY IF EXISTS announcement_insert      ON public.announcement;
DROP POLICY IF EXISTS announcement_update      ON public.announcement;
DROP POLICY IF EXISTS announcement_delete      ON public.announcement;

CREATE POLICY announcement_owner_read ON public.announcement
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin()));

-- A scheduled post is invisible to members until its time — here, not in the UI.
CREATE POLICY announcement_member_read ON public.announcement
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_member_space_ids()) AND publish_at <= now());

CREATE POLICY announcement_insert ON public.announcement
  FOR INSERT TO app_backend
  WITH CHECK (author_id = app.current_user_id() AND app.owns_active_space(space_id));

CREATE POLICY announcement_update ON public.announcement
  FOR UPDATE TO app_backend
  USING      (author_id = app.current_user_id() AND app.owns_active_space(space_id))
  WITH CHECK (author_id = app.current_user_id() AND app.owns_active_space(space_id));

CREATE POLICY announcement_delete ON public.announcement
  FOR DELETE TO app_backend
  USING (author_id = app.current_user_id() AND app.owns_active_space(space_id));

REVOKE UPDATE ON public.announcement FROM app_backend;
GRANT  UPDATE (body, publish_at) ON public.announcement TO app_backend;

COMMENT ON COLUMN public.announcement.publish_at IS
  'When members may see the post. Defaults to now(); a future value schedules it, enforced by '
  'announcement_member_read. Movable only while still in the future (service rule).';
