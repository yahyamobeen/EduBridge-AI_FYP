-- ============================================================================
-- EduBridge AI — the second-factor lookup that login actually needs
-- Implements : tdd.md §3.1 (login discriminator), §6.9 (SEC-14)
--
-- THE BUG THIS FIXES
--
--   `login()` decided which of the three statuses to return by reading
--   `two_factor_enrollment` with a plain SELECT. Login runs BEFORE a session
--   exists, so `app.current_user_id()` is unset, so `two_factor_enrollment_owner`
--   matched nothing and the read returned ZERO ROWS — every time, for every
--   user. Not an error. Not a warning. Just an empty result that the code read
--   as "this account has no second factor yet".
--
--   Two consequences, both bad:
--
--     1. A user with ACTIVE TOTP was told `two_factor_enrollment_required` and
--        handed an enrolment token instead of a challenge. `/2fa/enroll` then
--        correctly refused, because ITS read of the same table happens after
--        the user is bound and therefore sees the truth. The account became
--        unreachable: correct password, correct authenticator, no way in.
--
--     2. The lockout check in `login()` read `locked_until` from the same empty
--        result, so it never fired. The ladder in `two_factor_enrollment` was
--        enforced at /2fa/verify and silently skipped at login.
--
--   This is the failure mode the whole RLS design is built around and warns
--   about in every other file: unset binding means zero rows, and zero rows
--   looks exactly like "nothing to see here".
--
-- Narrow on purpose, like the rest of 20260802140000: three columns, the ones
-- the login discriminator needs, and nothing else. No secret, no counter.
--
-- RE-RUNNABLE: CREATE OR REPLACE, REVOKE/GRANT.
-- ============================================================================

CREATE OR REPLACE FUNCTION app.lookup_2fa_for_login(p_user_id uuid)
RETURNS TABLE (
  method       two_factor_method,
  status       two_factor_status,
  locked_until timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT e.method, e.status, e.locked_until
  FROM public.two_factor_enrollment e
  WHERE e.user_id = p_user_id;
$$;

REVOKE ALL ON FUNCTION app.lookup_2fa_for_login(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.lookup_2fa_for_login(uuid) TO app_backend;

COMMENT ON FUNCTION app.lookup_2fa_for_login(uuid) IS
  'POST /api/auth/login. Which second factor to challenge, and whether the '
  'account is locked. Login has no bound user, so a plain SELECT on '
  'two_factor_enrollment returns zero rows and reads as "not enrolled" — which '
  'sent every enrolled user to enrolment and skipped the lockout entirely. '
  'Returns no secret and no counter: the challenge itself uses '
  'app.start_2fa_challenge.';
