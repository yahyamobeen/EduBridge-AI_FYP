-- ============================================================================
-- EduBridge AI — app.change_password() (Phase 3, FR-A8 / tdd.md:194)
--
-- WHY A FUNCTION AND NOT AN UPDATE. `20260816160000:63-66` recorded this as a
-- standing consequence of finding B3: that migration revoked table-wide UPDATE
-- on `app_user` and granted `full_name` only, so `password_hash` is no longer
-- writable by `app_backend` at all. That is deliberate — a password write
-- should go through something that ALSO ends every existing session, not
-- through a grant that happens to permit it.
--
-- ⚠️ IT TAKES NO USER IDENTIFIER, BY DECISION (repository owner, 2026-08-16).
--    The plan specified `change_password(p_user_id uuid, p_new_password_hash
--    text)` guarded by `p_user_id = app.current_user_id()`. That is the shape of
--    finding **C1** — a SECURITY DEFINER function accepting a caller-chosen user
--    — with a check bolted on, and a check can be dropped by a later edit that
--    looks like a simplification. Deriving the user from the bound session
--    removes the parameter instead, so the whole class is unreachable here:
--    there is nothing to pass and nothing to verify.
--
--    This works ONLY because this endpoint is authenticated. `SECURITY DEFINER`
--    changes the executing ROLE, not the session's configuration settings, so
--    `app.current_user_id()` still reads what `set_current_user_id()` bound for
--    this transaction (the same reasoning as 20260816180000, finding C2). The
--    pre-authentication functions cannot do this and that is why C1 needs a
--    redesign rather than a check.
--
-- ⚠️ THE RETURN SHAPE IS TWO FIELDS BECAUSE ONE CANNOT SAY WHAT HAPPENED.
--    "Rows revoked" alone is ambiguous: **0 means both "refused" and "changed,
--    but the user had no live sessions"**, and a caller writing the natural
--    `if not result:` would read a refusal as a success and report 204 while
--    the password never changed. `changed` answers the security question and
--    `tokens_revoked` answers the audit one.
--
-- FAIL-CLOSED AT EVERY EXIT. No bound user -> (false, 0). No matching row
-- (deleted account, or a binding that does not correspond to a live user) ->
-- (false, 0). The session revocation runs only after the password write is
-- confirmed to have hit a row, so a refusal can never revoke anybody's tokens.
--
-- ⚠️ VERIFYING THE CURRENT PASSWORD STAYS IN PYTHON. argon2 lives there
--    (`app.auth.security.verify_password`) and the hash is READABLE through the
--    ordinary bound session — §2.2 revoked UPDATE, never SELECT, so
--    `app_user_self_read` still serves it. After the column-grant work the
--    instinct is to reach for a privileged function for every `app_user`
--    access; here that would be wrong, and it would put a password comparison
--    inside a function that runs as the owner.
--
-- CALL SITES: one, `change_password` in `backend/app/auth/service.py`, reached
-- from `POST /api/auth/password/change`. New function, so there are no existing
-- callers to walk.
--
-- MODELLED ON `app.consume_password_reset_token` (20260803120000:447-489),
-- which performs the same two writes. The difference is where the authority
-- comes from: that one is authorised by a single-use token, this one by the
-- bound session.
--
-- Idempotent: `CREATE OR REPLACE`, and the permission statements are no-ops
-- when already in force.
-- ============================================================================

CREATE OR REPLACE FUNCTION app.change_password(p_new_password_hash text)
RETURNS TABLE (changed boolean, tokens_revoked integer)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id uuid := app.current_user_id();
  v_changed integer := 0;
  v_revoked integer := 0;
BEGIN
  -- No bound session. Reachable only through a bug, and it must not be a
  -- silent no-op that the caller reports as success.
  IF v_user_id IS NULL THEN
    RETURN QUERY SELECT false, 0;
    RETURN;
  END IF;

  UPDATE public.app_user
     SET password_hash = p_new_password_hash,
         updated_at    = now()
   WHERE id         = v_user_id
     AND deleted_at IS NULL;
  GET DIAGNOSTICS v_changed = ROW_COUNT;

  -- ⚠️ RETURN BEFORE REVOKING. If the password write matched nothing, revoking
  --    sessions would log a user out on the strength of a change that did not
  --    happen.
  IF v_changed = 0 THEN
    RETURN QUERY SELECT false, 0;
    RETURN;
  END IF;

  -- A password change ends every existing session — the same rule
  -- `consume_password_reset_token` applies (20260803120000:480-485). Refresh
  -- tokens only: the access token is stateless and outlives this by up to its
  -- TTL. Closing that window is Phase 4's `sessions_invalidated_at`, and it is
  -- deliberately NOT smuggled in here.
  UPDATE public.auth_token
     SET revoked = true
   WHERE user_id = v_user_id
     AND kind    = 'refresh'
     AND revoked = false;
  GET DIAGNOSTICS v_revoked = ROW_COUNT;

  RETURN QUERY SELECT true, v_revoked;
END;
$$;

-- ============================================================================
-- Permissions.
--
-- ⚠️ A NEW FUNCTION IS EXECUTABLE BY PUBLIC BY DEFAULT. That is finding C5,
--    closed across seven functions in 20260816190000, and omitting the REVOKE
--    below reopens it on the one function in the schema that rewrites a
--    password. `app_backend` is granted explicitly rather than left to inherit.
-- ============================================================================
REVOKE ALL     ON FUNCTION app.change_password(text) FROM PUBLIC;
GRANT EXECUTE  ON FUNCTION app.change_password(text) TO app_backend;

COMMENT ON FUNCTION app.change_password(text) IS
  'POST /api/auth/password/change. Rewrites the bound user''s password_hash and '
  'revokes their refresh family. Takes NO user identifier: the subject is '
  'app.current_user_id(), so it cannot be aimed at another account (contrast '
  'finding C1). Returns (changed, tokens_revoked) because 0 revoked tokens is a '
  'legitimate success. Verifying the CURRENT password is the caller''s job and '
  'happens in Python, where argon2 lives.';
