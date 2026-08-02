-- ============================================================================
-- EduBridge AI — reference-data reads, pre-auth lookups, and a missed FORCE
-- Implements : tdd.md §3.1 (auth), §6.8 (RLS)
--
-- WHY THIS EXISTS
--   20260801120100_rls_policies.sql enables AND forces RLS on every table in
--   `public`, then writes policies for 36 of them. Six reference/curriculum
--   tables were never given one, so they are DENY-ALL for app_backend:
--
--       board · class_level · subject · subject_group · chapter · slo
--
--   Nothing about that is per-user; it is a gap, not a decision. It is why
--   /api/reference/enums had to be served through the RLS-bypassing service
--   role, and it would equally have blocked the tutor, quiz and coverage work.
--
--   `question_key` is also policy-less and MUST STAY THAT WAY. That one is
--   deliberate: answer keys are unreadable by the application role by design
--   (NFR-8 database backstop). Do not "fix" it here.
--
-- ORDERING NOTE
--   This file must be applied AFTER 20260802120000_subscriptions_and_oauth.sql,
--   which is already applied to the project but lives on the frontend branch.
--   Apply from a tree that contains both, i.e. after the branches merge.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Reference and curriculum data is readable by the application role.
--
-- SELECT ONLY, deliberately. app_backend already holds INSERT/UPDATE/DELETE
-- grants on every table (rls_policies.sql), so with no write policy those
-- verbs stay denied — which is what stops the application mutating curriculum.
-- A `FOR ALL` policy here would quietly hand it that power. Curriculum writes
-- belong to the ingestion pipeline running as the service role.
-- ----------------------------------------------------------------------------

CREATE POLICY board_read ON public.board
  FOR SELECT TO app_backend USING (true);

CREATE POLICY class_level_read ON public.class_level
  FOR SELECT TO app_backend USING (true);

CREATE POLICY subject_read ON public.subject
  FOR SELECT TO app_backend USING (true);

CREATE POLICY subject_group_read ON public.subject_group
  FOR SELECT TO app_backend USING (true);

CREATE POLICY chapter_read ON public.chapter
  FOR SELECT TO app_backend USING (true);

CREATE POLICY slo_read ON public.slo
  FOR SELECT TO app_backend USING (true);

-- ----------------------------------------------------------------------------
-- 2. FORCE RLS on the subscription tables.
--
-- 20260802120000 enabled row level security on these three but did not FORCE
-- it, unlike every other table in the schema. Exposure is small — the
-- application connects as app_backend, which is not the owner — but the
-- convention exists precisely so that "owner bypasses RLS" is never a factor
-- anyone has to reason about.
-- ----------------------------------------------------------------------------

ALTER TABLE public.subscription      FORCE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_plan FORCE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_identity    FORCE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. Pre-authentication lookups.
--
-- THE PROBLEM THESE SOLVE
--   `app_user_self_read` is USING (id = app.current_user_id()) and
--   `auth_token_owner` is USING (user_id = app.current_user_id()). Both are
--   unsatisfiable before authentication — and login and refresh are, by
--   definition, before authentication. There is no user id to set yet.
--
-- WHY NOT JUST CONNECT AS THE SERVICE ROLE
--   Because then the bypass is implicit in a connection and spreads: it was
--   already being used for /auth/me's identity check, which runs on every
--   authenticated request. These functions make the exception explicit,
--   auditable, and narrow — each returns only the columns its flow needs.
--
-- WHY NOT A POLICY LIKE `USING (app.current_user_id() IS NULL)`
--   It would work, and it would be a trap. Today a forgotten SET LOCAL yields
--   zero rows; with that policy it would yield EVERY user's row. Fail-closed
--   would become fail-open on exactly the code path most likely to carry the
--   bug. Rejected on purpose.
--
-- SECURITY DEFINER, same pattern as app.is_admin() above, which already reads
-- app_user this way under FORCE RLS. Execution is revoked from PUBLIC and
-- granted only to app_backend; neither takes dynamic SQL.
-- ============================================================================

-- Returns the minimum needed to verify a password and decide the login status.
-- Deliberately NOT SELECT *: nothing else about the user belongs on this path.
CREATE OR REPLACE FUNCTION app.lookup_user_for_login(p_email text)
RETURNS TABLE (
  id                uuid,
  password_hash     text,
  status            user_status,
  email_verified_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT u.id, u.password_hash, u.status, u.email_verified_at
  FROM public.app_user u
  WHERE lower(u.email) = lower(p_email)
    AND u.deleted_at IS NULL;
$$;

-- Returns the token row for rotation. The caller compares hashes; this never
-- accepts or returns a plaintext token.
CREATE OR REPLACE FUNCTION app.lookup_refresh_token(p_token_hash text)
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
  WHERE t.token_hash = p_token_hash;
$$;

-- Rotation and revocation also happen before a session exists, so the writes
-- need the same treatment. Kept separate from the read so that a caller which
-- only needs to look something up cannot also revoke.
CREATE OR REPLACE FUNCTION app.revoke_auth_token(p_id uuid)
RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  UPDATE public.auth_token SET revoked = true WHERE id = p_id;
$$;

-- Breach response: reusing an already-revoked refresh token means the token
-- was captured, so the whole family goes. Returns how many were revoked so the
-- caller can audit it.
CREATE OR REPLACE FUNCTION app.revoke_refresh_family(p_user_id uuid)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  affected integer;
BEGIN
  UPDATE public.auth_token
     SET revoked = true
   WHERE user_id = p_user_id
     AND kind    = 'refresh'
     AND revoked = false;
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$;

-- Issued during refresh rotation, which is still pre-session.
CREATE OR REPLACE FUNCTION app.insert_auth_token(
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

REVOKE ALL ON FUNCTION app.lookup_user_for_login(text)                        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.lookup_refresh_token(text)                         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.revoke_auth_token(uuid)                            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.revoke_refresh_family(uuid)                        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.insert_auth_token(uuid, token_kind, text, timestamptz) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app.lookup_user_for_login(text)                        TO app_backend;
GRANT EXECUTE ON FUNCTION app.lookup_refresh_token(text)                         TO app_backend;
GRANT EXECUTE ON FUNCTION app.revoke_auth_token(uuid)                            TO app_backend;
GRANT EXECUTE ON FUNCTION app.revoke_refresh_family(uuid)                        TO app_backend;
GRANT EXECUTE ON FUNCTION app.insert_auth_token(uuid, token_kind, text, timestamptz) TO app_backend;

COMMENT ON FUNCTION app.lookup_user_for_login(text) IS
  'Pre-authentication user lookup for POST /api/auth/login. Returns only the '
  'columns needed to verify a password and derive the login status.';
COMMENT ON FUNCTION app.lookup_refresh_token(text) IS
  'Pre-authentication token lookup for POST /api/auth/refresh. Takes a hash; '
  'never a plaintext token.';
