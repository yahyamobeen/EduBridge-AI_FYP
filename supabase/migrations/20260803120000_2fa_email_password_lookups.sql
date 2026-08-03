-- ============================================================================
-- EduBridge AI — 2FA, email verification, and password reset lookups
-- Implements : tdd.md §3.1 (auth endpoints), §6.9 (SEC-14)
--
-- WHY THIS EXISTS
--   All eight endpoints in KAN-10b (2fa/enroll, 2fa/confirm, 2fa/verify,
--   2fa/resend, email/verify, email/resend, password/forgot, password/reset)
--   run BEFORE a session exists — there is no `app.current_user_id()` to
--   satisfy RLS policies. They reach the rows they need through these narrow
--   SECURITY DEFINER functions rather than through the RLS-bypassing service
--   connection.
--
-- CONVENTIONS (from 20260802140000)
--   * CREATE OR REPLACE — idempotent, so a partial Supabase CLI run can be
--     re-applied without "already exists" errors.
--   * SET search_path = public, pg_temp — prevents shadowing attacks.
--   * REVOKE ALL FROM PUBLIC, GRANT EXECUTE TO app_backend — nobody else
--     can call these.
--   * Each function returns ONLY the columns its flow needs.
--
-- DEPENDENCY ORDER
--   Must be applied after 20260802140100_token_kind_enrollment.sql, which
--   adds the two_factor_enrollment token_kind value used by several functions
--   below.
--
-- RE-RUNNABLE
--   Every statement is CREATE OR REPLACE or uses IF NOT EXISTS where
--   applicable. Safe to re-run after a partial failure.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Challenge token lookup (enrolment and pending)
--
-- Validates a challenge token by hash AND asserts the expected kind. This is
-- the single function that enforces the boundary between enrolment tokens
-- (~900s, good for /2fa/enroll and /2fa/confirm) and pending tokens (~300s,
-- good for /2fa/verify). An enrolment token presented at /2fa/verify returns
-- no row, and the caller raises PENDING_TOKEN_EXPIRED — which is the correct
-- response because the token was never valid for that purpose.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.lookup_challenge_token(
  p_token_hash text,
  p_kind       token_kind
)
RETURNS TABLE (
  id         uuid,
  user_id    uuid,
  kind       token_kind,
  revoked    boolean,
  expires_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT t.id, t.user_id, t.kind, t.revoked, t.expires_at
  FROM public.auth_token t
  WHERE t.token_hash = p_token_hash
    AND t.kind       = p_kind;
$$;


-- ----------------------------------------------------------------------------
-- 2. 2FA enrolment upsert
--
-- INSERT ON CONFLICT so that re-calling /2fa/enroll (the implicit resend,
-- tdd.md §14.4 finding 2) overwrites the pending secret rather than creating
-- a second row. Resets failed_attempts and locked_until so a user who
-- mistyped during a previous enrolment attempt starts fresh.
--
-- For TOTP: p_secret_encrypted is the Fernet ciphertext.
-- For email_otp: p_secret_encrypted is NULL (enforced by ck_email_otp_has_no_secret).
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.upsert_2fa_enrollment(
  p_user_id            uuid,
  p_method             two_factor_method,
  p_secret_encrypted   bytea
)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  INSERT INTO public.two_factor_enrollment (user_id, method, totp_secret_encrypted)
  VALUES (p_user_id, p_method, p_secret_encrypted)
  ON CONFLICT (user_id) DO UPDATE
     SET method                = EXCLUDED.method,
         totp_secret_encrypted = EXCLUDED.totp_secret_encrypted,
         status                = 'pending',
         confirmed_at          = NULL,
         last_used_at          = NULL,
         last_used_counter     = NULL,
         failed_attempts       = 0,
         locked_until          = NULL,
         updated_at            = now();
$$;


-- ----------------------------------------------------------------------------
-- 3. Activate 2FA
--
-- Called by /2fa/confirm after the first code is verified. Sets status=active
-- and records the confirmation timestamp. The CHECK constraint
-- ck_active_is_confirmed ensures this cannot produce an active row without a
-- confirmed_at — the database enforces the invariant, not just the code.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.activate_2fa(p_user_id uuid)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.two_factor_enrollment
     SET status       = 'active',
         confirmed_at = now(),
         updated_at   = now()
   WHERE user_id = p_user_id;
$$;


-- ----------------------------------------------------------------------------
-- 4. Replace backup codes
--
-- Atomic swap: deletes every existing code for the user, inserts the new set.
-- The old codes are gone the instant the new ones exist — there is no window
-- where both sets are valid. Takes a text array of pre-hashed codes (argon2id
-- hashes, uppercased before hashing for case-insensitive comparison).
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.replace_backup_codes(
  p_user_id uuid,
  p_hashes  text[]
)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  h text;
  inserted integer := 0;
BEGIN
  DELETE FROM public.two_factor_backup_code WHERE user_id = p_user_id;
  FOREACH h IN ARRAY p_hashes LOOP
    INSERT INTO public.two_factor_backup_code (user_id, code_hash)
    VALUES (p_user_id, h);
    inserted := inserted + 1;
  END LOOP;
  RETURN inserted;
END;
$$;


-- ----------------------------------------------------------------------------
-- 5. Start 2FA challenge
--
-- Validates the challenge token (not revoked, not expired) and joins to
-- two_factor_enrollment to return everything /2fa/verify needs in one call:
-- the enrolled method, the encrypted TOTP secret, the replay-guard counter,
-- the current failure count, and any active lockout.
--
-- If the token is invalid (wrong kind, revoked, expired, unknown), returns
-- zero rows. The caller treats that as PENDING_TOKEN_EXPIRED.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.start_2fa_challenge(
  p_token_hash text,
  p_kind       token_kind
)
RETURNS TABLE (
  token_user_id         uuid,
  token_id              uuid,
  method                two_factor_method,
  status                two_factor_status,
  totp_secret_encrypted bytea,
  last_used_counter     bigint,
  failed_attempts       smallint,
  locked_until          timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT t.user_id, t.id, e.method, e.status,
         e.totp_secret_encrypted, e.last_used_counter,
         e.failed_attempts, e.locked_until
  FROM public.auth_token t
  JOIN public.two_factor_enrollment e ON e.user_id = t.user_id
  WHERE t.token_hash = p_token_hash
    AND t.kind       = p_kind
    AND t.revoked    = false
    AND t.expires_at > now();
$$;


-- ----------------------------------------------------------------------------
-- 6. Record successful 2FA verification
--
-- Resets the failure counter, records the current time and the TOTP
-- time-step counter (for replay guard). The counter is NULL for email_otp
-- and backup_code verifications, which are single-use and do not need one.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.verify_2fa_success(
  p_user_id uuid,
  p_counter bigint   -- NULL for email_otp and backup_code
)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.two_factor_enrollment
     SET failed_attempts   = 0,
         last_used_at      = now(),
         last_used_counter = COALESCE(p_counter, last_used_counter),
         locked_until      = NULL,
         updated_at        = now()
   WHERE user_id = p_user_id;
$$;


-- ----------------------------------------------------------------------------
-- 7. Record failed 2FA verification
--
-- Increments the failure counter and optionally sets locked_until. The caller
-- computes the lockout duration from the threshold table (tdd.md §6.9, D7).
-- A NULL p_locked_until means the threshold has not been reached yet.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.verify_2fa_failure(
  p_user_id      uuid,
  p_failed       smallint,
  p_locked_until timestamptz   -- NULL when no lockout
)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.two_factor_enrollment
     SET failed_attempts = p_failed,
         locked_until    = p_locked_until,
         updated_at      = now()
   WHERE user_id = p_user_id;
$$;


-- ----------------------------------------------------------------------------
-- 8. Consume a backup code
--
-- Sets used_at on the matching code. The unique constraint
-- uq_backup_code is on (user_id, code_hash), so this can only affect one row.
-- Returns 1 if a row was updated, 0 if the hash did not match (which the
-- caller interprets as "wrong code").
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.consume_backup_code(
  p_user_id   uuid,
  p_code_hash text
)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  affected integer;
BEGIN
  UPDATE public.two_factor_backup_code
     SET used_at = now()
   WHERE user_id  = p_user_id
     AND code_hash = p_code_hash
     AND used_at   IS NULL;
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$;


-- ----------------------------------------------------------------------------
-- 9. Get unused backup codes
--
-- Returns all unused code hashes for a user, so /2fa/verify can compare a
-- submitted backup code against them. Only hashes — never plaintext.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.get_unused_backup_codes(p_user_id uuid)
RETURNS TABLE (code_hash text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT b.code_hash
  FROM public.two_factor_backup_code b
  WHERE b.user_id = p_user_id
    AND b.used_at IS NULL;
$$;


-- ----------------------------------------------------------------------------
-- 10. Issue email OTP
--
-- Revokes all prior unrevoked two_factor_email_otp tokens for the user
-- (each new OTP invalidates the previous one), then inserts a new token row.
-- The OTP is a 6-digit code hashed with HMAC-SHA256 before storage.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.issue_email_otp(
  p_user_id    uuid,
  p_token_hash text,
  p_expires_at timestamptz
)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  new_id uuid;
BEGIN
  UPDATE public.auth_token
     SET revoked = true
   WHERE user_id = p_user_id
     AND kind    = 'two_factor_email_otp'
     AND revoked = false;

  INSERT INTO public.auth_token (user_id, kind, token_hash, expires_at)
  VALUES (p_user_id, 'two_factor_email_otp', p_token_hash, p_expires_at)
  RETURNING id INTO new_id;

  RETURN new_id;
END;
$$;


-- ----------------------------------------------------------------------------
-- 11. Lookup email OTP
--
-- Finds an unrevoked, unexpired email OTP token matching the given hash for
-- the given user. Returns zero rows if no match — the caller treats that as
-- "wrong code".
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.lookup_email_otp(
  p_user_id    uuid,
  p_code_hash  text
)
RETURNS TABLE (id uuid, user_id uuid, expires_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT t.id, t.user_id, t.expires_at
  FROM public.auth_token t
  WHERE t.user_id    = p_user_id
    AND t.token_hash = p_code_hash
    AND t.kind       = 'two_factor_email_otp'
    AND t.revoked    = false
    AND t.expires_at > now();
$$;


-- ----------------------------------------------------------------------------
-- 12. Consume email verification token (idempotent)
--
-- Validates an email_verify token: must exist, not be revoked, not be expired.
-- On success: sets email_verified_at, revokes the token, returns the user_id.
--
-- IDEMPOTENT: if the token was already consumed (revoked=true) but the user's
-- email is already verified, returns the user_id without error. This handles
-- the mail-client-prefetch scenario (tdd.md §14.4 finding 4) — a verification
-- link is commonly opened twice, and the second click should not show an error.
--
-- If the token is unknown (never existed) or expired and the email is NOT
-- verified, returns zero rows. The caller raises INVALID_TOKEN or
-- TOKEN_EXPIRED accordingly.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.consume_token_and_verify_email(p_token_hash text)
RETURNS TABLE (user_id uuid, already_verified boolean)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_token_id   uuid;
  v_user_id    uuid;
  v_revoked    boolean;
  v_expired    boolean;
  v_verified   boolean;
BEGIN
  -- Look up the token (any state).
  SELECT t.id, t.user_id, t.revoked, t.expires_at <= now()
    INTO v_token_id, v_user_id, v_revoked, v_expired
  FROM public.auth_token t
  WHERE t.token_hash = p_token_hash
    AND t.kind       = 'email_verify';

  -- Token not found at all.
  IF v_token_id IS NULL THEN
    RETURN;  -- zero rows -> caller raises INVALID_TOKEN
  END IF;

  -- Check if the email is already verified (regardless of token state).
  SELECT (u.email_verified_at IS NOT NULL)
    INTO v_verified
  FROM public.app_user u
  WHERE u.id = v_user_id;

  -- Already consumed AND already verified -> idempotent success.
  IF v_revoked AND v_verified THEN
    RETURN QUERY SELECT v_user_id, true;
    RETURN;
  END IF;

  -- Token was revoked but email is NOT verified -> spent token, not idempotent.
  IF v_revoked THEN
    RETURN;  -- zero rows -> caller raises INVALID_TOKEN
  END IF;

  -- Token expired.
  IF v_expired THEN
    -- Even if expired, if email is already verified, return idempotent success.
    IF v_verified THEN
      RETURN QUERY SELECT v_user_id, true;
      RETURN;
    END IF;
    RETURN;  -- zero rows -> caller raises TOKEN_EXPIRED
  END IF;

  -- Valid token: verify the email and revoke the token.
  UPDATE public.app_user
     SET email_verified_at = now()
   WHERE id = v_user_id
     AND email_verified_at IS NULL;

  UPDATE public.auth_token
     SET revoked = true
   WHERE id = v_token_id;

  RETURN QUERY SELECT v_user_id, false;
END;
$$;


-- ----------------------------------------------------------------------------
-- 13. Consume password reset token
--
-- Validates a password_reset token (not revoked, not expired), updates the
-- password hash, revokes the token, and revokes ALL refresh tokens for the
-- user (a password change invalidates every existing session).
-- ----------------------------------------------------------------------------

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

  -- Update the password.
  UPDATE public.app_user
     SET password_hash = p_new_password_hash,
         updated_at    = now()
   WHERE id = v_user_id;

  -- Revoke the reset token.
  UPDATE public.auth_token SET revoked = true WHERE id = v_token_id;

  -- Revoke ALL refresh tokens (password change = every session dies).
  UPDATE public.auth_token
     SET revoked = true
   WHERE user_id = v_user_id
     AND kind    = 'refresh'
     AND revoked = false;

  RETURN true;
END;
$$;


-- ----------------------------------------------------------------------------
-- 14. Lookup user email and name
--
-- Narrow read for email-sending flows. Returns only (email, full_name) —
-- nothing else about the user belongs on this path.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.lookup_user_email(p_user_id uuid)
RETURNS TABLE (email citext, full_name text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.email, u.full_name
  FROM public.app_user u
  WHERE u.id = p_user_id
    AND u.deleted_at IS NULL;
$$;


-- ----------------------------------------------------------------------------
-- 15. Issue token for email flows
--
-- Thin wrapper around INSERT for email_verify and password_reset tokens.
-- These flows run before a session exists, so they need a SECURITY DEFINER
-- path to write auth_token rows.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.issue_token_for_email(
  p_user_id    uuid,
  p_kind       token_kind,
  p_token_hash text,
  p_expires_at timestamptz
)
RETURNS uuid
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  INSERT INTO public.auth_token (user_id, kind, token_hash, expires_at)
  VALUES (p_user_id, p_kind, p_token_hash, p_expires_at)
  RETURNING id;
$$;


-- ----------------------------------------------------------------------------
-- 16. Check token status (pre-auth)
--
-- Used by /email/verify and /password/reset to distinguish between an expired
-- token (410 TOKEN_EXPIRED) and an unknown/invalid token (400 INVALID_TOKEN)
-- when the main consume function returns zero rows.
--
-- Without this, a direct SELECT on auth_token would return zero rows under RLS
-- (no user bound), making it impossible to distinguish "token never existed"
-- from "token exists but is expired".
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app.check_token_status(
  p_token_hash text,
  p_kind       token_kind
)
RETURNS TABLE (
  token_found boolean,
  token_expired boolean,
  token_user_id uuid
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT
    true AS token_found,
    (t.expires_at <= now()) AS token_expired,
    t.user_id AS token_user_id
  FROM public.auth_token t
  WHERE t.token_hash = p_token_hash
    AND t.kind = p_kind;
$$;


-- ============================================================================
-- Permissions: revoke from PUBLIC, grant to app_backend.
-- ============================================================================

REVOKE ALL ON FUNCTION app.lookup_challenge_token(text, token_kind)         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.upsert_2fa_enrollment(uuid, two_factor_method, bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.activate_2fa(uuid)                               FROM PUBLIC;
REVOKE ALL ON FUNCTION app.replace_backup_codes(uuid, text[])               FROM PUBLIC;
REVOKE ALL ON FUNCTION app.start_2fa_challenge(text, token_kind)            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.verify_2fa_success(uuid, bigint)                 FROM PUBLIC;
REVOKE ALL ON FUNCTION app.verify_2fa_failure(uuid, smallint, timestamptz)   FROM PUBLIC;
REVOKE ALL ON FUNCTION app.consume_backup_code(uuid, text)                  FROM PUBLIC;
REVOKE ALL ON FUNCTION app.get_unused_backup_codes(uuid)                    FROM PUBLIC;
REVOKE ALL ON FUNCTION app.issue_email_otp(uuid, text, timestamptz)         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_email_otp(uuid, text)                     FROM PUBLIC;
REVOKE ALL ON FUNCTION app.consume_token_and_verify_email(text)             FROM PUBLIC;
REVOKE ALL ON FUNCTION app.consume_password_reset_token(text, text)         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_user_email(uuid)                          FROM PUBLIC;
REVOKE ALL ON FUNCTION app.issue_token_for_email(uuid, token_kind, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.check_token_status(text, token_kind)              FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app.lookup_challenge_token(text, token_kind)         TO app_backend;
GRANT EXECUTE ON FUNCTION app.upsert_2fa_enrollment(uuid, two_factor_method, bytea) TO app_backend;
GRANT EXECUTE ON FUNCTION app.activate_2fa(uuid)                               TO app_backend;
GRANT EXECUTE ON FUNCTION app.replace_backup_codes(uuid, text[])               TO app_backend;
GRANT EXECUTE ON FUNCTION app.start_2fa_challenge(text, token_kind)            TO app_backend;
GRANT EXECUTE ON FUNCTION app.verify_2fa_success(uuid, bigint)                 TO app_backend;
GRANT EXECUTE ON FUNCTION app.verify_2fa_failure(uuid, smallint, timestamptz)   TO app_backend;
GRANT EXECUTE ON FUNCTION app.consume_backup_code(uuid, text)                  TO app_backend;
GRANT EXECUTE ON FUNCTION app.get_unused_backup_codes(uuid)                    TO app_backend;
GRANT EXECUTE ON FUNCTION app.issue_email_otp(uuid, text, timestamptz)         TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_email_otp(uuid, text)                     TO app_backend;
GRANT EXECUTE ON FUNCTION app.consume_token_and_verify_email(text)             TO app_backend;
GRANT EXECUTE ON FUNCTION app.consume_password_reset_token(text, text)         TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_user_email(uuid)                          TO app_backend;
GRANT EXECUTE ON FUNCTION app.issue_token_for_email(uuid, token_kind, text, timestamptz) TO app_backend;
GRANT EXECUTE ON FUNCTION app.check_token_status(text, token_kind)              TO app_backend;
