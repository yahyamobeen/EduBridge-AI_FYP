-- ============================================================================
-- EduBridge AI — session policy functions (Phase 4: findings E2, E3, D2)
--
-- Four things, all of which need the columns from `20260817120000`:
--
--   app.invalidate_sessions      NEW, internal — stamps sessions_invalidated_at
--   app.insert_refresh_token     NEW — mints a token that STARTS a family
--   app.rotate_refresh_token     NEW — atomic exchange; fixes D2
--   (replaced) revoke_refresh_family, consume_password_reset_token,
--              change_password  — each now also invalidates access tokens
--
-- ============================================================================
-- ⚠️ `clock_timestamp()`, NEVER `now()`. THE WHOLE PHASE TURNS ON THIS.
--
--    `now()` is `transaction_timestamp()` and is FROZEN for the entire
--    transaction. Measured in this project: 0.0s of movement across 3 real
--    seconds, while `clock_timestamp()` advanced 3.24s.
--
--    A stamp written with `now()` lands at the transaction's START, so an access
--    token minted later in the SAME transaction carries a LATER issue time and
--    survives the invalidation that was supposed to kill it. Worse, the
--    integration suite runs inside one outer transaction with savepoint nesting,
--    so `now()` is pinned to test start and the test PASSES while asserting
--    nothing. That is the single most expensive mistake available here.
-- ============================================================================
--
-- ⚠️ THREE OF THE FOUR INVALIDATION EVENTS HAVE NO BOUND USER, which is why the
--    stamp lives inside these functions and not in Python. Password reset and
--    reuse revocation run on `get_db`, which binds nobody, so a plain
--    `UPDATE app_user SET sessions_invalidated_at = ...` matches ZERO rows under
--    `app_user_self_update` — and raises nothing. It would look like it worked.
--
-- ⚠️ NO NEW PARAMETER ON `app.insert_auth_token`. `CREATE OR REPLACE` with an
--    added defaulted argument creates a SECOND function; the existing
--    four-argument call at `tokens.py:54` then matches both and PostgreSQL
--    raises "function name is not unique" at runtime, not at migration time.
--    Hence new NAMES. `insert_auth_token` is untouched and still serves the five
--    non-refresh kinds.
--
-- ⚠️ `app.lookup_refresh_token` IS DELIBERATELY UNCHANGED — a DEVIATION FROM THE
--    PLAN, and it removes a risk rather than taking one. The plan had it
--    drop-and-recreate to return `family_started_at`, which would have taken its
--    `REVOKE ... FROM PUBLIC`, `GRANT` and `COMMENT` with it (the trap
--    `20260816140000` fell into). It is unnecessary: `app.rotate_refresh_token`
--    reads the family itself under the same lock, and returns the user id, so
--    `refresh()` no longer needs the read-back that motivated the change.
--
-- ⚠️ `app.revoke_refresh_family` KEEPS ITS `(uuid)` SIGNATURE AND ITS `integer`
--    RETURN. Adding a `p_reason` argument with a default would create the same
--    overload ambiguity described above, and `test_tokens.py:127-137` asserts
--    the return value is exactly `2`. Its one caller is reuse detection, so the
--    reason is a constant inside the body.
--
-- Idempotent: every statement is `CREATE OR REPLACE` or a REVOKE/GRANT of a
-- privilege already in force.
-- ============================================================================


-- ── app.invalidate_sessions ─────────────────────────────────────────────────
-- The single definition of "every access token issued before now is dead".
--
-- ⚠️ IT IS NOT GRANTED TO `app_backend`, ON PURPOSE. It takes a user id, so a
--    grant would let any authenticated caller sign any other user out — a
--    denial of service, not a takeover, but exactly the caller-chosen-subject
--    shape of finding C1. Only the owner can execute it, which means only the
--    three SECURITY DEFINER functions below can, since they run as the owner.
--    If a future endpoint genuinely needs this, it should get its own narrow
--    function that derives the subject from `app.current_user_id()` — the way
--    `app.change_password` does.
CREATE OR REPLACE FUNCTION app.invalidate_sessions(p_user_id uuid)
RETURNS timestamptz
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_at timestamptz := clock_timestamp();
BEGIN
  UPDATE public.app_user
     SET sessions_invalidated_at = v_at
   WHERE id = p_user_id;
  -- Returned so the caller can thread it into the token it is about to mint,
  -- which is provably safe regardless of clock skew between statements.
  RETURN v_at;
END;
$$;

REVOKE ALL ON FUNCTION app.invalidate_sessions(uuid) FROM PUBLIC;
-- Deliberately NO grant to app_backend. See above.

COMMENT ON FUNCTION app.invalidate_sessions(uuid) IS
  'Stamps app_user.sessions_invalidated_at with clock_timestamp() and returns it. '
  'INTERNAL: executable only by the owner, so only the SECURITY DEFINER functions '
  'that revoke sessions can call it. Never granted to app_backend, because a '
  'caller-chosen user id is finding C1''s shape.';


-- ── app.insert_refresh_token ────────────────────────────────────────────────
-- Mints the token that BEGINS a rotating family. Login and 2FA verification
-- call this; every subsequent token in the chain comes from
-- `app.rotate_refresh_token`, which carries the family start forward.
CREATE OR REPLACE FUNCTION app.insert_refresh_token(
  p_user_id    uuid,
  p_token_hash text,
  p_expires_at timestamptz
)
RETURNS uuid
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  INSERT INTO public.auth_token
    (user_id, kind, token_hash, expires_at, family_started_at)
  VALUES
    (p_user_id, 'refresh', p_token_hash, p_expires_at, clock_timestamp())
  RETURNING id;
$$;

REVOKE ALL     ON FUNCTION app.insert_refresh_token(uuid, text, timestamptz) FROM PUBLIC;
GRANT EXECUTE  ON FUNCTION app.insert_refresh_token(uuid, text, timestamptz) TO app_backend;

COMMENT ON FUNCTION app.insert_refresh_token(uuid, text, timestamptz) IS
  'Mints a refresh token that STARTS a family, stamping family_started_at with '
  'clock_timestamp(). A separate name rather than an argument on '
  'insert_auth_token, because a defaulted argument would create an overload the '
  'existing four-argument call matches ambiguously.';


-- ── app.rotate_refresh_token ────────────────────────────────────────────────
-- Finding **D2**, and the absolute session cap, in one place.
--
-- BEFORE: `tokens.py` did read -> check -> revoke -> insert as four round trips
-- with no lock. Two concurrent refreshes presenting the same token could both
-- pass the `revoked` check: one FORKED the family (defeating any cap), and the
-- other tripped reuse detection on a legitimate refresh. The client's
-- single-flight guard is per browser TAB, so two tabs reproduce it.
--
-- The `FOR UPDATE` below is what makes it atomic. Under READ COMMITTED the
-- second caller blocks on the lock and then re-reads the row, so it sees the
-- revocation the winner just made — it cannot also succeed.
CREATE OR REPLACE FUNCTION app.rotate_refresh_token(
  p_old_hash       text,
  p_new_hash       text,
  p_expires_at     timestamptz,
  p_family_max_age interval,
  p_race_grace     interval
)
RETURNS TABLE (outcome text, token_user_id uuid, family_started_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_id         uuid;
  v_user       uuid;
  v_revoked    boolean;
  v_revoked_at timestamptz;
  v_expires    timestamptz;
  v_family     timestamptz;
  v_now        timestamptz := clock_timestamp();
BEGIN
  SELECT t.id, t.user_id, t.revoked, t.revoked_at, t.expires_at,
         -- COALESCE for tokens minted before 20260817120000 existed. The
         -- backfill covers live ones; this covers anything it missed.
         coalesce(t.family_started_at, t.created_at)
    INTO v_id, v_user, v_revoked, v_revoked_at, v_expires, v_family
    FROM public.auth_token t
   WHERE t.token_hash = p_old_hash
     AND t.kind       = 'refresh'
     FOR UPDATE;

  IF v_id IS NULL THEN
    RETURN QUERY SELECT 'not_found'::text, NULL::uuid, NULL::timestamptz;
    RETURN;
  END IF;

  IF v_revoked THEN
    -- ⚠️ A RACE, NOT A THEFT — but only under BOTH conditions. The revocation
    --    must be seconds old AND a live sibling of the same family must still
    --    exist, which together mean "the winner of a concurrent refresh already
    --    replaced this token". A captured token replayed later, or after the
    --    family was revoked, fails one of the two and falls through to reuse.
    IF v_revoked_at IS NOT NULL
       AND v_revoked_at > v_now - p_race_grace
       AND EXISTS (
         SELECT 1 FROM public.auth_token s
          WHERE s.user_id           = v_user
            AND s.kind              = 'refresh'
            AND s.revoked           = false
            AND s.family_started_at = v_family
       )
    THEN
      RETURN QUERY SELECT 'raced'::text, v_user, v_family;
      RETURN;
    END IF;

    RETURN QUERY SELECT 'reuse'::text, v_user, v_family;
    RETURN;
  END IF;

  IF v_expires <= v_now THEN
    RETURN QUERY SELECT 'expired'::text, v_user, v_family;
    RETURN;
  END IF;

  -- The absolute ceiling. Rotation without one means a chain can be extended
  -- for ever, seven days at a time, so no session anybody keeps using ever
  -- expires. The limit is passed in rather than hard-coded so that
  -- `settings.session_absolute_ttl_days` stays the single definition.
  IF v_family + p_family_max_age <= v_now THEN
    UPDATE public.auth_token
       SET revoked        = true,
           revoked_at     = v_now,
           revoked_reason = 'family_expired'
     WHERE id = v_id;
    RETURN QUERY SELECT 'family_expired'::text, v_user, v_family;
    RETURN;
  END IF;

  UPDATE public.auth_token
     SET revoked        = true,
         revoked_at     = v_now,
         revoked_reason = 'rotated'
   WHERE id = v_id;

  INSERT INTO public.auth_token
    (user_id, kind, token_hash, expires_at, family_started_at)
  VALUES
    (v_user, 'refresh', p_new_hash, p_expires_at, v_family);

  RETURN QUERY SELECT 'rotated'::text, v_user, v_family;
END;
$$;

REVOKE ALL ON FUNCTION
  app.rotate_refresh_token(text, text, timestamptz, interval, interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  app.rotate_refresh_token(text, text, timestamptz, interval, interval) TO app_backend;

COMMENT ON FUNCTION app.rotate_refresh_token(text, text, timestamptz, interval, interval) IS
  'Atomic refresh rotation (finding D2). Locks the old row FOR UPDATE, so two '
  'concurrent refreshes cannot both succeed and fork the family. Enforces the '
  'absolute family age cap. Distinguishes a two-tab RACE (revoked within the '
  'grace window, live sibling still present -> plain 401) from a token THEFT '
  '(-> the caller revokes the family). Outcomes: rotated, raced, reuse, expired, '
  'family_expired, not_found.';


-- ── Replaced: the three revocation paths now end access tokens too ──────────
-- Revoking refresh tokens ends the ability to obtain a NEW access token and
-- does nothing about the one already in the caller's memory, which stays valid
-- for up to `access_token_ttl_minutes`. Until now a password change left an
-- attacker signed in for another quarter of an hour.

CREATE OR REPLACE FUNCTION app.revoke_refresh_family(p_user_id uuid)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  affected integer;
  v_now    timestamptz := clock_timestamp();
BEGIN
  UPDATE public.auth_token
     SET revoked        = true,
         revoked_at     = v_now,
         revoked_reason = 'reuse_detected'
   WHERE user_id = p_user_id
     AND kind    = 'refresh'
     AND revoked = false;
  GET DIAGNOSTICS affected = ROW_COUNT;

  -- Token theft is exactly the case where the stolen ACCESS token matters most.
  PERFORM app.invalidate_sessions(p_user_id);

  -- ⚠️ STILL RETURNS THE COUNT, AND STILL AS `integer`.
  --    `test_tokens.py:127-137` asserts it is 2. Changing the return type here
  --    would also have required a DROP, taking the REVOKE, GRANT and COMMENT
  --    from 20260802140000 with it.
  RETURN affected;
END;
$$;

CREATE OR REPLACE FUNCTION app.consume_password_reset_token(
  p_token_hash        text,
  p_new_password_hash text
)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_token_id uuid;
  v_user_id  uuid;
  v_now      timestamptz := clock_timestamp();
BEGIN
  SELECT t.id, t.user_id
    INTO v_token_id, v_user_id
  FROM public.auth_token t
  WHERE t.token_hash = p_token_hash
    AND t.kind       = 'password_reset'
    AND t.revoked    = false
    AND t.expires_at > now();

  IF v_token_id IS NULL THEN
    RETURN false;
  END IF;

  UPDATE public.app_user
     SET password_hash = p_new_password_hash,
         updated_at    = now()
   WHERE id = v_user_id;

  UPDATE public.auth_token
     SET revoked        = true,
         revoked_at     = v_now,
         revoked_reason = 'password_reset'
   WHERE id = v_token_id;

  UPDATE public.auth_token
     SET revoked        = true,
         revoked_at     = v_now,
         revoked_reason = 'password_reset'
   WHERE user_id = v_user_id
     AND kind    = 'refresh'
     AND revoked = false;

  -- The point of a reset is that whoever had the account no longer does.
  PERFORM app.invalidate_sessions(v_user_id);

  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION app.change_password(p_new_password_hash text)
RETURNS TABLE (changed boolean, tokens_revoked integer)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_user_id uuid := app.current_user_id();
  v_changed integer := 0;
  v_revoked integer := 0;
  v_now     timestamptz := clock_timestamp();
BEGIN
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

  IF v_changed = 0 THEN
    RETURN QUERY SELECT false, 0;
    RETURN;
  END IF;

  UPDATE public.auth_token
     SET revoked        = true,
         revoked_at     = v_now,
         revoked_reason = 'password_change'
   WHERE user_id = v_user_id
     AND kind    = 'refresh'
     AND revoked = false;
  GET DIAGNOSTICS v_revoked = ROW_COUNT;

  -- 20260816210000 said this window was Phase 4's to close and deliberately did
  -- not smuggle it in. This is Phase 4.
  PERFORM app.invalidate_sessions(v_user_id);

  RETURN QUERY SELECT true, v_revoked;
END;
$$;

-- `CREATE OR REPLACE` keeps the grants and comments on all three, since no
-- signature or return type changed. Re-stated for change_password only, because
-- it is the one whose comment now understates what it does.
COMMENT ON FUNCTION app.change_password(text) IS
  'POST /api/auth/password/change. Rewrites the bound user''s password_hash, '
  'revokes their refresh family, and stamps sessions_invalidated_at so the '
  'access token already in the attacker''s hands dies too (Phase 4). Takes NO '
  'user identifier: the subject is app.current_user_id(), so it cannot be aimed '
  'at another account. Returns (changed, tokens_revoked) because 0 revoked '
  'tokens is a legitimate success.';
