-- ============================================================================
-- EduBridge AI — the guardian_link write boundary
-- Implements : prd.md §4.3 parental gate; tdd.md §3.1 anti-forgery
--
-- WHY THIS EXISTS
--
--   `rls_policies.sql` L188 claims of guardian_link that "neither may forge a
--   verified status (the API sets status after out-of-band verification)". The
--   policies did not enforce that claim, and the applied database had drifted
--   from the file in a way that broke a live code path. Both are fixed here.
--
--   1. THE DIVERGENCE. `rls_policies.sql` L205-207 writes guardian_link_update
--      as `USING (parent_id = ... OR student_id = ...)`. The APPLIED policy is
--      `USING (parent_id = app.current_user_id())` with a matching WITH CHECK
--      — parent-only. `guardian_invite()` reset an existing link to 'pending'
--      with an UPDATE issued as the STUDENT, which therefore matched zero rows
--      and failed SILENTLY: re-inviting after a link was revoked returned
--      `{"invite_sent": true, "status": "pending"}` while the link stayed
--      `revoked`, and the parent's fresh invitation was then rejected by
--      app.confirm_guardian_link (which only transitions 'pending'). The
--      student had no way back through the API. Verified against the live
--      project by probing pg_policies and driving the endpoint.
--
--      The fix is NOT to widen the policy. A student who can UPDATE their own
--      link can set status='verified', verified_at=now() and clear their own
--      gate — the forgery the whole control exists to prevent. The reset moves
--      to app.reinvite_guardian_link instead, which can only ever write
--      'pending'.
--
--   2. THE FORGERY HOLE. guardian_link_create's WITH CHECK constrains WHO is on
--      the row but not WHAT STATUS it is born with, so either participant could
--      INSERT a row that is already 'verified' (measured: allowed). No endpoint
--      exposes it today, which is exactly why it should be closed before one
--      does.
--
--   After this migration a link can reach 'verified' through EXACTLY ONE path:
--   app.confirm_guardian_link, which requires an unexpired, unrevoked, one-time
--   guardian_invite token. Every other write is 'pending' or 'revoked'.
--   SECURITY DEFINER functions are unaffected by these policies — they run as
--   the owning role, which is how the confirm path still works.
--
-- SUPERSEDES `20260801120100_rls_policies.sql` L198-207 for these two policies.
-- That file is applied and is deliberately NOT edited here; read pg_policies,
-- not the file, for what is live.
--
-- RE-RUNNABLE ON PURPOSE (the Supabase CLI does not wrap migrations in a
-- transaction): DROP IF EXISTS + CREATE, CREATE OR REPLACE, REVOKE/GRANT.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. A link is born pending. Nothing may INSERT one that is already verified.
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS guardian_link_create ON public.guardian_link;
CREATE POLICY guardian_link_create ON public.guardian_link
  FOR INSERT TO app_backend
  WITH CHECK (
    (student_id = app.current_user_id() OR parent_id = app.current_user_id())
    AND parent_id <> student_id
    AND status = 'pending'
  );

-- ----------------------------------------------------------------------------
-- 2. Only the parent may UPDATE (unchanged from what is live — restated so the
--    file and the database agree), and no direct UPDATE may produce 'verified'.
--    This leaves a parent able to withdraw consent (-> 'revoked') without being
--    able to grant it, which is the asymmetry the gate needs.
-- ----------------------------------------------------------------------------
DROP POLICY IF EXISTS guardian_link_update ON public.guardian_link;
CREATE POLICY guardian_link_update ON public.guardian_link
  FOR UPDATE TO app_backend
  USING (parent_id = app.current_user_id())
  WITH CHECK (parent_id = app.current_user_id() AND status <> 'verified');

-- ----------------------------------------------------------------------------
-- 3. The re-invite reset. The student owns the invitation but cannot UPDATE the
--    link, so this is the narrow privileged path — same pattern as
--    20260802140000 and 20260802150000: one statement, no dynamic SQL, exposing
--    strictly less than the caller could otherwise reach.
--
--    `status <> 'verified'` is a hard guard, not an optimisation: a re-invite
--    must never be able to undo a completed verification, even if a caller
--    reaches this with the wrong arguments. Returns the resulting status, or
--    NULL when nothing was updated (no such link, or it is already verified) so
--    the caller can fail loudly instead of reporting a success that did not
--    happen.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.reinvite_guardian_link(
  p_student uuid, p_parent uuid
) RETURNS guardian_status
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.guardian_link
     SET status              = 'pending',
         verification_method = NULL,
         verified_at         = NULL
   WHERE student_id = p_student
     AND parent_id  = p_parent
     AND status    <> 'verified'
  RETURNING status;
$$;

REVOKE ALL ON FUNCTION app.reinvite_guardian_link(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.reinvite_guardian_link(uuid, uuid) TO app_backend;

COMMENT ON FUNCTION app.reinvite_guardian_link(uuid, uuid) IS
  'POST /api/auth/guardian/invite, resend path. Resets an existing non-verified '
  'guardian_link to pending. The student cannot UPDATE guardian_link directly '
  '(parent-only policy), and widening that policy would let a student forge '
  'their own verification. Returns NULL when no row was reset.';
