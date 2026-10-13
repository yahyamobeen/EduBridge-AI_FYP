-- ============================================================================
-- EduBridge AI — the class chat (classroom Phase 7)
--
-- prd.md §15 CL-5 (v0.4.0), tdd.md §3.6. A CLASS-PUBLIC channel for the teacher
-- and the current members — never private messaging. Every safeguard CL-5
-- requires is a DATABASE fact here, not a service habit:
--
--   * Who may post is the INSERT policy, through app.can_post_message: an
--     active, UNMUTED member of an UNLOCKED, ACTIVE classroom who passes the
--     Class 9–10 guardian gate — or its teacher, who may post while it is locked.
--   * The teacher deletes any message, but a deleted message is RETAINED
--     (deleted_at / deleted_by): members stop reading it, the teacher (and an
--     administrator) still can.
--   * Mute is enrollment.muted_at (added by 20261004120000 for this phase);
--     the lock is classroom_space.chat_locked.
--
-- The table is `space_message`, NEVER `message`: the tutor conversation stays
-- owner-only (tdd.md §6.8, prd.md §4.2), and sharing a table would put the two
-- under one set of policies.
--
-- `created_at` is clock_timestamp(), not now(): now() is frozen per
-- transaction, and the poll's cursor needs the real insert time. It, `id` and
-- the moderation columns are not insertable (a column grant), so a message's
-- time and its deletion cannot be forged.
--
-- `author_id` is ON DELETE RESTRICT (owner decision 2026-10-05): deleting an
-- account does not delete what it said in a class.
--
-- Idempotent: IF NOT EXISTS column, table and indexes, policies dropped before
-- they are created, CREATE OR REPLACE functions.
-- ============================================================================

-- ── 1. The lock ─────────────────────────────────────────────────────────────
ALTER TABLE public.classroom_space
  ADD COLUMN IF NOT EXISTS chat_locked boolean NOT NULL DEFAULT false;
-- Written through space_owner_update (20261004120000), like title and status:
-- the owner, with an unrevoked subject scope.
GRANT UPDATE (chat_locked) ON public.classroom_space TO app_backend;

COMMENT ON COLUMN public.classroom_space.chat_locked IS
  'PATCH /api/spaces/{id}. While true only the teacher posts in the class chat '
  '(app.can_post_message); members still read it.';

-- ── 2. Table ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.space_message (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id   uuid        NOT NULL REFERENCES public.classroom_space(id) ON DELETE CASCADE,
  author_id  uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  body       text        NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  deleted_at timestamptz,
  deleted_by uuid        REFERENCES public.app_user(id) ON DELETE RESTRICT,
  CONSTRAINT ck_space_message_body CHECK (char_length(btrim(body)) BETWEEN 1 AND 1000),
  -- Deleted means deleted BY someone: never one without the other.
  CONSTRAINT ck_space_message_deleted_pair CHECK ((deleted_at IS NULL) = (deleted_by IS NULL))
);
-- The feed, both directions: first load and "older" read it backwards, the
-- poll forwards.
CREATE INDEX IF NOT EXISTS ix_space_message_feed
  ON public.space_message (space_id, created_at, id);
-- Tombstones: what was deleted since the last poll.
CREATE INDEX IF NOT EXISTS ix_space_message_deleted
  ON public.space_message (space_id, deleted_at) WHERE deleted_at IS NOT NULL;
-- Both foreign keys to app_user are RESTRICT; an index keeps each check off a
-- full scan (ix_grade_graded_by, 20261004140000).
CREATE INDEX IF NOT EXISTS ix_space_message_author ON public.space_message (author_id);
CREATE INDEX IF NOT EXISTS ix_space_message_deleted_by
  ON public.space_message (deleted_by) WHERE deleted_by IS NOT NULL;

COMMENT ON TABLE public.space_message IS
  'The class chat (prd.md CL-5). Class-public; NOT the tutor `message` table, which stays '
  'owner-only. Soft-deleted by the teacher and retained for review.';

-- ── 3. Grants ───────────────────────────────────────────────────────────────
-- ALTER DEFAULT PRIVILEGES (20260801120100:38) granted SELECT, INSERT, UPDATE
-- and DELETE; narrow it. Posting is a column-limited INSERT under the policy
-- below; deleting is app.delete_space_message; nothing is ever UPDATEd or
-- DELETEd directly.
REVOKE INSERT, UPDATE, DELETE ON public.space_message FROM app_backend;
GRANT  SELECT ON public.space_message TO app_backend;
GRANT  INSERT (space_id, author_id, body) ON public.space_message TO app_backend;

ALTER TABLE public.space_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.space_message FORCE  ROW LEVEL SECURITY;

-- ── 4. Who may post ─────────────────────────────────────────────────────────
-- POST /api/spaces/{id}/messages — the INSERT policy, and the poll's can_post.
-- Fails closed: no such classroom answers false.
CREATE OR REPLACE FUNCTION app.can_post_message(p_space uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT COALESCE((
    SELECT CASE
             WHEN s.status <> 'active'   THEN false
             -- The teacher moderates, so a lock does not silence them.
             WHEN app.owns_space(s.id)   THEN true
             WHEN s.chat_locked          THEN false
             ELSE EXISTS (SELECT 1 FROM public.enrollment e
                           WHERE e.space_id = s.id
                             AND e.student_id = app.current_user_id()
                             AND e.left_at IS NULL
                             AND e.muted_at IS NULL)
                  -- Class 9–10: the gate, again at the DATABASE layer.
                  AND app.caller_passes_guardian_gate()
           END
      FROM public.classroom_space s
     WHERE s.id = p_space
  ), false);
$$;

-- ── 5. Policies ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS space_message_owner_read  ON public.space_message;
DROP POLICY IF EXISTS space_message_member_read ON public.space_message;
DROP POLICY IF EXISTS space_message_insert      ON public.space_message;

-- The teacher reads everything, deleted messages included (retained for
-- review); an administrator too (prd.md §4.2, no interface in v1).
CREATE POLICY space_message_owner_read ON public.space_message
  FOR SELECT TO app_backend
  USING (space_id IN (SELECT app.my_owned_space_ids()) OR (SELECT app.is_admin()));

-- A current member reads what has not been deleted. Muted or not, locked or
-- not: those stop posting, never reading.
CREATE POLICY space_message_member_read ON public.space_message
  FOR SELECT TO app_backend
  USING (deleted_at IS NULL AND space_id IN (SELECT app.my_member_space_ids()));

CREATE POLICY space_message_insert ON public.space_message
  FOR INSERT TO app_backend
  WITH CHECK (author_id = app.current_user_id() AND app.can_post_message(space_id));

-- ── 6. Moderation ───────────────────────────────────────────────────────────
-- DELETE /api/messages/{id}. Soft, and it works on an archived classroom:
-- moderation does not stop when posting does. Deleting twice is not an error.
CREATE OR REPLACE FUNCTION app.delete_space_message(p_message uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_row record;
BEGIN
  SELECT m.space_id, m.deleted_at INTO v_row
    FROM public.space_message m
   WHERE m.id = p_message
     FOR UPDATE;
  IF NOT FOUND OR NOT app.owns_space(v_row.space_id) THEN
    RETURN 'forbidden';
  END IF;
  IF v_row.deleted_at IS NOT NULL THEN
    RETURN 'already_deleted';
  END IF;
  UPDATE public.space_message
     SET deleted_at = clock_timestamp(), deleted_by = app.current_user_id()
   WHERE id = p_message;
  RETURN 'deleted';
END;
$$;

-- PUT /api/spaces/{id}/members/{student_id}/mute. A current member only. The
-- first mute's time is kept; unmuting clears it. Leaving and rejoining keeps a
-- mute (app.join_space_by_code, 20261004120100).
CREATE OR REPLACE FUNCTION app.set_student_muted(p_space uuid, p_student uuid, p_muted boolean)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT app.owns_space(p_space) THEN
    RETURN false;
  END IF;
  UPDATE public.enrollment
     SET muted_at = CASE WHEN p_muted THEN COALESCE(muted_at, clock_timestamp()) END
   WHERE space_id = p_space AND student_id = p_student AND left_at IS NULL;
  RETURN FOUND;
END;
$$;

-- GET /api/spaces/{id}/messages. A member cannot read a deleted row, so the
-- poll learns of deletions here: ids only, never content, and only for the
-- classroom's teacher and current members.
CREATE OR REPLACE FUNCTION app.space_message_tombstones(p_space uuid, p_since timestamptz)
RETURNS TABLE (message_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  WITH me AS (SELECT app.owns_space(p_space) OR app.is_enrolled_in(p_space) AS ok)
  SELECT m.id
    FROM public.space_message m
   CROSS JOIN me
   WHERE me.ok
     AND m.space_id = p_space
     AND m.deleted_at > p_since;
$$;

-- ── 7. Grants and comments ──────────────────────────────────────────────────
-- can_post_message is granted because a POLICY calls it (20260816190000:41-45)
-- as well as the service.
REVOKE ALL ON FUNCTION app.can_post_message(uuid)                        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.delete_space_message(uuid)                    FROM PUBLIC;
REVOKE ALL ON FUNCTION app.set_student_muted(uuid, uuid, boolean)        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.space_message_tombstones(uuid, timestamptz)   FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.can_post_message(uuid)                     TO app_backend;
GRANT EXECUTE ON FUNCTION app.delete_space_message(uuid)                 TO app_backend;
GRANT EXECUTE ON FUNCTION app.set_student_muted(uuid, uuid, boolean)     TO app_backend;
GRANT EXECUTE ON FUNCTION app.space_message_tombstones(uuid, timestamptz) TO app_backend;

COMMENT ON FUNCTION app.can_post_message(uuid) IS
  'RLS insert predicate (space_message_insert) and GET /api/spaces/{id}/messages can_post. '
  'Active classroom; its teacher always; otherwise an unlocked chat and an active, unmuted '
  'member who passes the guardian gate. Fails closed.';
COMMENT ON FUNCTION app.delete_space_message(uuid) IS
  'DELETE /api/messages/{id}. Teacher of the classroom only; soft (retained). Outcomes: '
  'deleted | already_deleted | forbidden. Allowed on an archived classroom.';
COMMENT ON FUNCTION app.set_student_muted(uuid, uuid, boolean) IS
  'PUT /api/spaces/{id}/members/{student_id}/mute. Teacher of the classroom only; a current '
  'member only. Returns false otherwise.';
COMMENT ON FUNCTION app.space_message_tombstones(uuid, timestamptz) IS
  'GET /api/spaces/{id}/messages. Ids of messages deleted since a time, for the teacher and '
  'current members only — never content.';
