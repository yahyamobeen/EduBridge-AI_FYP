-- ============================================================================
-- EduBridge AI — 2FA lockout integrity, TOTP replay guard, email locale
-- Implements : tdd.md §6.9 (SEC-14 D7), §3.1; prd.md §3.1 (Urdu-first)
--
-- CORRECTIVE. 20260803120000 is APPLIED, so its functions are replaced here
-- rather than edited in place. Five changes:
--
--   1. `upsert_2fa_enrollment` STOPS CLEARING THE LOCKOUT. It reset
--      `failed_attempts = 0, locked_until = NULL` on conflict, and the client's
--      enrolment "resend" is a re-call of /2fa/enroll (tdd.md §14.4 finding 2)
--      — so a locked enrolment was cleared by reloading the page. That is the
--      exact failure mode a lockout exists to prevent. The counters now survive
--      a re-enrol; only a successful verification clears them
--      (`verify_2fa_success`), which is the one event that proves possession.
--
--   2. `activate_2fa` RECORDS THE TOTP COUNTER just consumed. Enrolment
--      verified the first code and stored nothing, so `last_used_counter` was
--      NULL until the first successful challenge — leaving the code that
--      completed enrolment replayable at /2fa/verify for its whole ±1 window.
--
--   3. `check_token_status` RETURNS `revoked`. Without it a spent-but-unexpired
--      token and an unknown token are indistinguishable to the caller, and an
--      expired-and-spent one reported TOKEN_EXPIRED when INVALID_TOKEN is the
--      truthful answer.
--
--   4. NEW `lookup_user_for_email_flow` — one narrow read for the two
--      enumeration-sensitive endpoints (password/forgot, email/resend). It
--      returns the stored address (so mail goes to the account's address, not
--      to the attacker-supplied spelling of it) and `language_pref`, which the
--      templates need: every verification and reset link was hardcoded to /en/
--      in an Urdu-first product.
--
--   5. `issue_token_for_email` is DROPPED. It was a byte-for-byte duplicate of
--      `app.insert_auth_token` from 20260802140000 — same parameters, same
--      body, same return — and two names for one privileged INSERT is one more
--      thing to keep in step.
--
-- RE-RUNNABLE: CREATE OR REPLACE, DROP IF EXISTS, REVOKE/GRANT throughout.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Enrolment upsert that cannot launder a lockout.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.upsert_2fa_enrollment(
  p_user_id          uuid,
  p_method           two_factor_method,
  p_secret_encrypted bytea
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
         -- failed_attempts and locked_until are NOT reset. Re-enrolling is a
         -- page reload; it must not buy a fresh set of guesses.
         updated_at            = now();
$$;

-- ----------------------------------------------------------------------------
-- 2. Activation records the consumed TOTP counter (NULL for email_otp).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.activate_2fa(p_user_id uuid, p_counter bigint DEFAULT NULL)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.two_factor_enrollment
     SET status            = 'active',
         confirmed_at      = now(),
         last_used_at      = now(),
         last_used_counter = p_counter,
         failed_attempts   = 0,
         locked_until      = NULL,
         updated_at        = now()
   WHERE user_id = p_user_id;
$$;

-- ----------------------------------------------------------------------------
-- 3. Token status, now including revocation.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.check_token_status(
  p_token_hash text,
  p_kind       token_kind
)
RETURNS TABLE (
  token_found   boolean,
  token_expired boolean,
  token_revoked boolean,
  token_user_id uuid
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT true, (t.expires_at <= now()), t.revoked, t.user_id
  FROM public.auth_token t
  WHERE t.token_hash = p_token_hash
    AND t.kind       = p_kind;
$$;

-- ----------------------------------------------------------------------------
-- 4. One read for the enumeration-sensitive email flows.
--
--    `language_pref` lives on student_profile, so it is a LEFT JOIN and is NULL
--    for teachers, parents and admins — the caller falls back to 'en'. Returns
--    the STORED email so delivery never depends on the caller's spelling.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.lookup_user_for_email_flow(p_email text)
RETURNS TABLE (
  id                uuid,
  email             citext,
  full_name         text,
  language_pref     language_code,
  email_verified_at timestamptz,
  status            user_status
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.id, u.email, u.full_name, sp.language_pref, u.email_verified_at, u.status
  FROM public.app_user u
  LEFT JOIN public.student_profile sp ON sp.user_id = u.id
  WHERE lower(u.email) = lower(p_email)
    AND u.deleted_at IS NULL;
$$;

-- ----------------------------------------------------------------------------
-- 5. Retire the duplicate insert path.
-- ----------------------------------------------------------------------------
DROP FUNCTION IF EXISTS app.issue_token_for_email(uuid, token_kind, text, timestamptz);

-- ============================================================================
-- Permissions.
-- ============================================================================
REVOKE ALL ON FUNCTION app.upsert_2fa_enrollment(uuid, two_factor_method, bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.activate_2fa(uuid, bigint)                            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.check_token_status(text, token_kind)                   FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_user_for_email_flow(text)                       FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app.upsert_2fa_enrollment(uuid, two_factor_method, bytea) TO app_backend;
GRANT EXECUTE ON FUNCTION app.activate_2fa(uuid, bigint)                            TO app_backend;
GRANT EXECUTE ON FUNCTION app.check_token_status(text, token_kind)                   TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_user_for_email_flow(text)                       TO app_backend;

COMMENT ON FUNCTION app.upsert_2fa_enrollment(uuid, two_factor_method, bytea) IS
  'POST /api/auth/2fa/enroll. Creates or replaces a PENDING enrolment. Never '
  'clears failed_attempts or locked_until: re-enrolling is a page reload and '
  'must not launder a lockout.';
COMMENT ON FUNCTION app.activate_2fa(uuid, bigint) IS
  'POST /api/auth/2fa/confirm. Activates the enrolment and seeds '
  'last_used_counter with the TOTP step just consumed, so the enrolment code '
  'cannot be replayed at /2fa/verify.';
COMMENT ON FUNCTION app.lookup_user_for_email_flow(text) IS
  'POST /api/auth/password/forgot and /email/resend. Returns the stored address '
  'and language_pref for locale-correct delivery.';
