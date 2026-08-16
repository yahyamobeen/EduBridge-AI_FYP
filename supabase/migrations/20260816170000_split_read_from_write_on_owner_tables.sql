-- ============================================================================
-- EduBridge AI — split read from write on the owner tables (B5, B6, B7)
--
-- Seven policies were `FOR ALL` with ownership as the only predicate, so "this
-- row is yours" also meant "you may rewrite it and delete it". Every expression
-- below is reproduced from `pg_policy` on the live database, not from the
-- migration files.
--
-- ⚠️ THE CALL-SITE WALK CHANGED THIS FILE'S SHAPE, and a naive version would
--    have broken registration and four token-revocation paths. The application
--    writes two of these tables DIRECTLY as `app_backend`, not through
--    privileged functions:
--
--      service.py:173    INSERT INTO subscription (user_id, plan_code) ...
--      service.py:905    UPDATE auth_token SET revoked = true WHERE id = <id>
--      service.py:927    UPDATE auth_token SET revoked = true WHERE id = <id>
--      service.py:1022   UPDATE auth_token SET revoked = true WHERE id = <id>
--      service.py:1058   UPDATE auth_token SET revoked = true WHERE id = <id>
--
--    (Written <id> rather than the real bind name on purpose: SQLAlchemy`s
--    text() parses a leading-colon token as a bind parameter EVEN INSIDE A SQL
--    COMMENT, so the literal form makes this file unexecutable from Python.)
--
--    The other five tables have NO writer anywhere — their endpoints belong to
--    later phases and do not exist. Verified by grep over `backend/app`.
--
-- ⚠️ B6 NEEDS A POLICY, NOT A COLUMN GRANT — the opposite conclusion from
--    20260816160000, and worth stating because the two files look similar.
--    `GRANT UPDATE (revoked)` would still permit `revoked = false`. Only a
--    `WITH CHECK` can express "this transition and not its inverse".
--
-- Idempotent: every policy is dropped before being created, and `REVOKE`/`GRANT`
-- of a privilege already in the target state is a no-op. The Supabase CLI does
-- not wrap a file in a transaction.
-- ============================================================================


-- ── subscription (B5) ───────────────────────────────────────────────────────
-- BEFORE: FOR ALL, USING/CHECK (user_id = app.current_user_id())
--         A user could set their own `status = 'active'` and a
--         `current_period_end` far enough out to satisfy
--         `ck_subscription_active_has_period`. That is the revenue model.
DROP POLICY IF EXISTS subscription_owner ON public.subscription;

CREATE POLICY subscription_read_own ON public.subscription
  FOR SELECT TO app_backend
  USING (user_id = app.current_user_id());

-- Registration creates the row; nothing else inserts one.
CREATE POLICY subscription_insert_own ON public.subscription
  FOR INSERT TO app_backend
  WITH CHECK (user_id = app.current_user_id());

-- AND the columns are narrowed, which is what actually stops a self-granted
-- subscription: with INSERT limited to these two, `status` and
-- `current_period_end` cannot be supplied at all and take their defaults.
-- `service.py:173` supplies exactly `user_id` and `plan_code`, so it is
-- unaffected.
REVOKE UPDATE ON public.subscription FROM app_backend;
REVOKE INSERT ON public.subscription FROM app_backend;
GRANT  INSERT (user_id, plan_code) ON public.subscription TO app_backend;

COMMENT ON POLICY subscription_read_own ON public.subscription IS
  'Owner reads their own subscription. There is deliberately NO update policy: '
  'activation follows payment and is written by the billing path as owner, '
  'never by the subscriber (finding B5).';


-- ── auth_token (B6) ─────────────────────────────────────────────────────────
-- BEFORE: FOR ALL, USING/CHECK (user_id = app.current_user_id())
--         Revocation was REVERSIBLE. Logout, password reset and the response to
--         detected token theft all work by setting `revoked = true`, and the
--         owner could set it back.
DROP POLICY IF EXISTS auth_token_owner ON public.auth_token;

CREATE POLICY auth_token_read_own ON public.auth_token
  FOR SELECT TO app_backend
  USING (user_id = app.current_user_id());

-- A ONE-WAY DOOR. The owner may revoke their own token and can never un-revoke
-- it, because the row must satisfy `revoked = true` AFTER the update. All four
-- application call sites set `revoked = true`, so none of them changes.
CREATE POLICY auth_token_revoke_own ON public.auth_token
  FOR UPDATE TO app_backend
  USING      (user_id = app.current_user_id())
  WITH CHECK (user_id = app.current_user_id() AND revoked = true);

-- Issuance stays with `app.insert_auth_token`, which is SECURITY DEFINER and
-- runs as owner: a token must never be mintable by the session that will use it.
REVOKE INSERT, DELETE ON public.auth_token FROM app_backend;

COMMENT ON POLICY auth_token_revoke_own ON public.auth_token IS
  'Revocation is one-way: WITH CHECK requires revoked = true, so the owner can '
  'kill a session and can never resurrect one (finding B6). A column grant on '
  '`revoked` would NOT have worked — it permits false as readily as true.';


-- ── the five student-data tables (B7) ───────────────────────────────────────
-- BEFORE: all FOR ALL with ownership as the only predicate.
--         These are exactly the numbers `coverage_viewers_read`,
--         `readiness_viewers_read`, `mastery_guardian_read` and
--         `attempt_teacher_read` show a parent or a teacher — so a student
--         could rewrite the evidence a guardian is shown about them.
--
-- No write policy is created, because NOTHING WRITES THEM YET. The phase that
-- builds the quiz and progress endpoints adds a narrow one, and the absence
-- here is a deliberate deny rather than an omission: `test_rls_coverage.py`
-- requires every table to keep at least one policy, so this stays visible.

DROP POLICY IF EXISTS attempt_student_own ON public.quiz_attempt;
CREATE POLICY attempt_read_own ON public.quiz_attempt
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

DROP POLICY IF EXISTS attempt_answer_owner ON public.attempt_answer;
CREATE POLICY attempt_answer_read_own ON public.attempt_answer
  FOR SELECT TO app_backend
  USING (EXISTS (
    SELECT 1 FROM quiz_attempt a
     WHERE a.id = attempt_answer.attempt_id
       AND a.student_id = app.current_user_id()
  ));

DROP POLICY IF EXISTS mastery_owner ON public.mastery_estimate;
CREATE POLICY mastery_read_own ON public.mastery_estimate
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

DROP POLICY IF EXISTS coverage_owner ON public.coverage_record;
CREATE POLICY coverage_read_own ON public.coverage_record
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

DROP POLICY IF EXISTS readiness_owner ON public.exam_readiness_score;
CREATE POLICY readiness_read_own ON public.exam_readiness_score
  FOR SELECT TO app_backend
  USING (student_id = app.current_user_id());

-- The grants follow the policies. A policy that permits nothing and a grant that
-- permits everything is a trap for whoever adds the next policy.
REVOKE INSERT, UPDATE, DELETE ON
  public.quiz_attempt,
  public.attempt_answer,
  public.mastery_estimate,
  public.coverage_record,
  public.exam_readiness_score
FROM app_backend;
