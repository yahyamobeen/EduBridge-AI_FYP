-- ============================================================================
-- EduBridge AI — the guardian functions check their caller (finding C2)
--
-- Both are `SECURITY DEFINER`, so they run as the owner and bypass Row-Level
-- Security entirely. Both took a user identifier and trusted it. The claim that
-- `guardian_link.status = 'verified'` is reachable by exactly one path — which
-- migration `20260803090000` spent an entire file establishing — rested on the
-- ONE CALL SITE passing the right argument, and on nothing in the database.
--
-- ⚠️ THE TWO FUNCTIONS HAVE DIFFERENT CALLERS, and swapping the checks would
--    break guardian invitations while looking correct:
--
--      app.reinvite_guardian_link(p_student, p_parent)
--        called from `guardian_invite(db, student_id, …)`  -> the STUDENT calls it
--        (`service.py:1327-1330`, `student_id` from AuthContext)
--
--      app.confirm_guardian_link(p_parent, p_token_hash)
--        called from `guardian_confirm(db, parent_id, …)`  -> the PARENT calls it
--        (`service.py:1415`, `parent_id` from AuthContext)
--
--    Verified by reading both call sites and both service signatures, not by
--    inferring from the parameter names.
--
-- WHY `app.current_user_id()` WORKS HERE AND NOT ELSEWHERE IN §2.7. These are
-- two of only THREE call sites in the whole application that run with a bound
-- session; every other privileged function runs pre-authentication and derives
-- its user from a token row resolved by hash, so it has no caller identity to
-- compare against. That is the whole reason they are SECURITY DEFINER. The
-- remaining C1 functions therefore need a redesign, not a check — see the phase
-- handoff.
--
-- `SECURITY DEFINER` changes the executing ROLE, not the session's configuration
-- settings, so `app.current_user_id()` still reads the value
-- `set_current_user_id()` bound for this transaction.
--
-- FAIL-CLOSED BY CONSTRUCTION. The check is added inside the CTE that finds the
-- link, so a caller who is not the party in question makes it empty: no UPDATE
-- runs, no token is consumed, and the function returns zero rows — which the
-- service already handles as "no such invitation". Nothing new to catch.
--
-- `CREATE OR REPLACE` is enough: neither signature nor return type changes, so
-- no grant or comment is lost. (Contrast `20260816140000`, where the return type
-- changed and the DROP took the REVOKE, GRANT and COMMENT with it.)
--
-- Idempotent: `CREATE OR REPLACE` is safe to re-run.
-- ============================================================================


-- ── app.confirm_guardian_link ───────────────────────────────────────────────
-- BEFORE: the `l` CTE matched on `parent_id = p_parent` alone, so ANY caller
--         holding a valid invitation token could confirm a link on behalf of
--         the parent it names.
CREATE OR REPLACE FUNCTION app.confirm_guardian_link(p_parent uuid, p_token_hash text)
RETURNS TABLE(status guardian_status, student_name text)
LANGUAGE sql SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
  WITH t AS (
    SELECT id, user_id FROM public.auth_token
    WHERE token_hash = p_token_hash
      AND kind = 'guardian_invite' AND revoked = false
      AND expires_at > now()
  ), l AS (
    SELECT id, status, student_id FROM public.guardian_link
    WHERE student_id = (SELECT user_id FROM t)
      AND parent_id = p_parent
      -- C2: the caller must BE the parent, not merely name one.
      AND p_parent = app.current_user_id()
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
$function$;

COMMENT ON FUNCTION app.confirm_guardian_link(uuid, text) IS
  'Parental-consent confirmation. SECURITY DEFINER because it runs before the '
  'link exists to authorise the read. `p_parent` must equal app.current_user_id() '
  '(finding C2) — without it, the "sole path to verified" guarantee rested on one '
  'call site passing the right argument and on nothing in the database.';


-- ── app.reinvite_guardian_link ──────────────────────────────────────────────
-- BEFORE: took two unverified identifiers and could resurrect a revoked link to
--         `pending` for any (student, parent) pair the caller chose.
CREATE OR REPLACE FUNCTION app.reinvite_guardian_link(p_student uuid, p_parent uuid)
RETURNS guardian_status
LANGUAGE sql SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
  UPDATE public.guardian_link
     SET status              = 'pending',
         verification_method = NULL,
         verified_at         = NULL
   WHERE student_id = p_student
     AND parent_id  = p_parent
     AND status    <> 'verified'
     -- C2: THE STUDENT is the caller here, not the parent. `guardian_invite`
     -- passes `student_id` from AuthContext.
     AND p_student = app.current_user_id()
  RETURNING status;
$function$;

COMMENT ON FUNCTION app.reinvite_guardian_link(uuid, uuid) IS
  'Resets a non-verified guardian link to pending so an invitation can be re-sent. '
  '`p_student` must equal app.current_user_id() (finding C2): the STUDENT invites, '
  'so the student is the caller. A verified link is never reset — that is the '
  'guarantee 20260803090000 established.';
