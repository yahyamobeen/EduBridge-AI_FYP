-- ============================================================================
-- EduBridge AI — guardian-gate privileged lookups + partition RLS hardening
-- Implements : prd.md §4.2 RBAC matrix, §4.3 parental gate; tdd.md §3.1, §6.8
--
-- TWO THINGS THIS FILE DOES
--
--   1. Closes a real RLS hole. 20260801120100's blanket ENABLE/FORCE loop skips
--      `%_default` tables, so the two DEFAULT partitions — `audit_log_default`
--      and `api_request_log_default` — were left with Row Level Security
--      DISABLED. `ENABLE ROW LEVEL SECURITY` does not cascade to partitions and
--      policies are per-table, so an app_backend connection could run
--      `SELECT * FROM audit_log_default` and read the whole audit trail past
--      `audit_admin_read`. Verified against PostgreSQL 17: enabling + forcing
--      RLS on a partition with no policies makes DIRECT access default-deny
--      while parent-routed inserts and selects keep using the parent's own
--      policies (which is why writes still land and `audit_admin_read` still
--      gates reads). Any future partition needs the same two ALTER TABLEs.
--
--   2. Adds the three narrow SECURITY DEFINER functions the guardian flow needs.
--      A student cannot read a parent's `app_user` row under `app_user_self_read`
--      and a parent cannot read the student's `auth_token` (its `user_id` is the
--      STUDENT) or `full_name` under owner-scoped RLS — so those reads, and the
--      atomic confirm write, go through functions that expose exactly the
--      columns their flow needs and nothing else. Same pattern as
--      20260802140000: REVOKE from PUBLIC, GRANT only to app_backend.
--
-- RE-RUNNABLE ON PURPOSE (Supabase CLI does not wrap migrations in a
-- transaction): every statement is idempotent — ALTER/CREATE OR REPLACE/
-- REVOKE/GRANT, and the policy change is DROP IF EXISTS + CREATE.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Partition RLS: default-deny on DIRECT access, untouched parent routing.
-- ----------------------------------------------------------------------------
ALTER TABLE public.audit_log_default      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log_default      FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.api_request_log_default ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_request_log_default FORCE  ROW LEVEL SECURITY;

-- ----------------------------------------------------------------------------
-- 2. Reconcile `app_user_insert` to the owner-scoped form.
--
--    The repo's 20260801120100 has `WITH CHECK (true)`; this migration applies
--    the stricter form to databases that already ran it. `register()` binds the
--    new id (set_current_user_id) BEFORE inserting (auth/service.py), so
--    `WITH CHECK (id = app.current_user_id())` is satisfied there. The point of
--    the strict form is fail-closed: a forgotten binding makes an INSERT fail
--    loudly instead of silently creating a user nobody can read back.
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS app_user_insert ON public.app_user;
CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend
  WITH CHECK (id = app.current_user_id());

-- ----------------------------------------------------------------------------
-- 3. Guardian privileged functions.
-- ----------------------------------------------------------------------------

-- Confirm: atomic single statement. Resolves the one-time invite token, and:
--   * token unknown / expired / revoked        -> 0 rows   (caller: 400 INVALID_TOKEN)
--   * link already verified                    -> ('verified', name); token NOT consumed
--                                                  (caller: 409 GUARDIAN_ALREADY_LINKED)
--   * link pending                             -> flips to verified + consumes token,
--                                                  returns ('pending', name) — the
--                                                  PRE-transition status, so the caller
--                                                  can tell "just verified" (200) from
--                                                  "already verified" (409).
--   * link revoked                             -> 0 rows   (a revoked link is not
--                                                  confirmable; a re-invite flips it
--                                                  back to pending first)
--
--   `l` is referenced by the data-modifying CTE `upd`, so PostgreSQL
--   MATERIALIZES it before the update runs — the returned status is guaranteed
--   to be the pre-update value, not the post-update one.
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

-- Status endpoint: the student cannot read the parent's app_user row, so this
-- returns the representative parent email for the student's links ('verified'
-- wins, latest created_at otherwise — the same ordering `me()` and
-- /auth/guardian/status use).
CREATE OR REPLACE FUNCTION app.lookup_guardian_parent_email(p_student uuid)
RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.email
    FROM public.guardian_link g
    JOIN public.app_user u ON u.id = g.parent_id
   WHERE g.student_id = p_student
   ORDER BY (g.status = 'verified') DESC, g.created_at DESC
   LIMIT 1;
$$;

-- Invite: resolve the parent's id by email. The student cannot read the
-- parent's app_user row under RLS, and a non-parent or inactive account must
-- never be linkable (the caller answers 422 GUARDIAN_NOT_FOUND when this
-- returns nothing).
CREATE OR REPLACE FUNCTION app.lookup_parent_id_by_email(p_email text)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.id
    FROM public.app_user u
   WHERE lower(u.email) = lower(p_email)
     AND u.role   = 'parent'
     AND u.status = 'active'
     AND u.deleted_at IS NULL
   LIMIT 1;
$$;

REVOKE ALL ON FUNCTION app.confirm_guardian_link(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_guardian_parent_email(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_parent_id_by_email(text)    FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app.confirm_guardian_link(uuid, text) TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_guardian_parent_email(uuid) TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_parent_id_by_email(text)    TO app_backend;

COMMENT ON FUNCTION app.confirm_guardian_link(uuid, text) IS
  'POST /api/auth/guardian/confirm. Consumes a one-time guardian_invite token '
  'and flips a pending guardian_link to verified atomically. Returns the link '
  'status BEFORE the transition so the caller can distinguish 200 from 409.';
COMMENT ON FUNCTION app.lookup_guardian_parent_email(uuid) IS
  'GET /api/auth/guardian/status. Representative parent email for a student''s '
  'links; the student cannot read the parent''s app_user row under RLS.';
COMMENT ON FUNCTION app.lookup_parent_id_by_email(text) IS
  'POST /api/auth/guardian/invite. Resolves an active parent account by email; '
  'the student cannot read the parent''s app_user row under RLS.';
