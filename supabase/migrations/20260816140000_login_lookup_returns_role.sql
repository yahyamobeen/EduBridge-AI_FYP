-- ============================================================================
-- EduBridge AI — app.lookup_user_for_login returns `role` (finding A6 / FR-A2a)
--
-- WHY: administrators must not authenticate at the public `POST /api/auth/login`.
-- They sign in at a separate endpoint, `POST /api/auth/admin/login`, reached
-- through an unlisted path. `login()` therefore has to know the caller's role
-- BEFORE it issues a challenge token — and the pre-authentication lookup did
-- not return one, so there was nothing to gate on.
--
-- ⚠️ THE SECRET URL IS NOT THE CONTROL. It is an unlisted door. The control is
--    this column and the two role checks it enables in `login()`: an
--    administrator is refused at the public endpoint, and a non-administrator is
--    refused at the admin endpoint. Both refusals are the SAME 401 with the same
--    body as a wrong password, because a distinguishable response would let
--    anyone enumerate which addresses are administrators by submitting them.
--
-- WHY A DROP AND NOT `CREATE OR REPLACE`: PostgreSQL refuses to replace a
-- function whose OUT parameters change — a `RETURNS TABLE` column list IS its
-- OUT parameters. `backend/CLAUDE.md` states the house rule this follows: drop
-- before changing a return type, and A DROP TAKES ITS GRANT AND COMMENT WITH IT.
--
-- ⚠️ THE DROP ALSO TAKES THE `REVOKE ... FROM PUBLIC` WITH IT, and that one is
--    easy to miss because nothing visibly breaks without it. A newly created
--    function is granted EXECUTE to PUBLIC by PostgreSQL's default, so omitting
--    the REVOKE below would silently make a pre-authentication lookup over
--    `app_user` callable by every role in the database. That is finding C5 —
--    five helper functions already carry that default — and this file must not
--    add a sixth. All four statements are re-issued together, deliberately.
--
-- CALL SITES WALKED BEFORE DROPPING (caller-and-callee rule): exactly one,
-- `backend/app/auth/service.py` in `login()`. It names its columns in the
-- SELECT list rather than using `SELECT *`, so an added column cannot shift a
-- tuple position under it. `grep -rn "lookup_user_for_login"` finds no other
-- Python, no view, no other function, and no trigger.
--
-- The body is unchanged apart from the added column: same WHERE clause, same
-- `deleted_at IS NULL`, same case-insensitive email match. Reproduced from
-- `pg_get_functiondef` on the live database rather than from the migration
-- file, so this cannot codify a definition that had drifted.
--
-- Idempotent: the Supabase CLI does not wrap a file in a transaction, so every
-- statement must be safe to re-run.
-- ============================================================================

-- BEFORE: TABLE(id, password_hash, status, email_verified_at)
DROP FUNCTION IF EXISTS app.lookup_user_for_login(text);

-- AFTER: the same four columns, plus `role`.
-- Still deliberately NOT `SELECT *`: nothing else about the user belongs on a
-- pre-authentication path.
CREATE FUNCTION app.lookup_user_for_login(p_email text)
RETURNS TABLE (
  id                uuid,
  password_hash     text,
  status            user_status,
  email_verified_at timestamptz,
  role              user_role
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.id, u.password_hash, u.status, u.email_verified_at, u.role
  FROM public.app_user u
  WHERE lower(u.email) = lower(p_email)
    AND u.deleted_at IS NULL;
$$;

-- RE-ISSUED BECAUSE THE DROP REMOVED THEM. Without the REVOKE the function is
-- executable by PUBLIC; without the GRANT every login answers 500 with
-- "permission denied for function lookup_user_for_login".
REVOKE ALL   ON FUNCTION app.lookup_user_for_login(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.lookup_user_for_login(text) TO app_backend;

COMMENT ON FUNCTION app.lookup_user_for_login(text) IS
  'Pre-authentication user lookup for POST /api/auth/login and '
  'POST /api/auth/admin/login. Returns only the columns needed to verify a '
  'password, derive the login status, and decide which of the two endpoints '
  'this account may authenticate at. `role` is here so that check happens in '
  'the query that was already being made, rather than as a second round trip '
  'on the hot login path.';
