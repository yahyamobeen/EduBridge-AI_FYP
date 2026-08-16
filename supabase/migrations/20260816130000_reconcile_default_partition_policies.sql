-- ============================================================================
-- EduBridge AI — reconcile the default-partition policies (finding F1)
--
-- FOUR POLICIES EXIST IN THE LIVE DATABASE AND IN NO MIGRATION. They were
-- applied by hand in the SQL editor and never written down. Found on 2026-08-16
-- by querying `pg_policy` and diffing the names against every file in
-- `supabase/migrations/` — the live count was 77 where the migrations produce 73.
--
-- WHY THIS IS NOT MERELY UNTIDY. `20260802150000:33-38` enables AND FORCES Row
-- Level Security on `audit_log_default` and `api_request_log_default`. A database
-- rebuilt from the migration files alone therefore has both partitions forced
-- with no policies at all, while production has four. Whatever the exact
-- consequence for routed writes, the two environments do not match, and the
-- migrations — which are supposed to be the source of truth — are the ones that
-- are wrong.
--
-- ⚠️ THIS FILE CODIFIES WHAT IS LIVE. It changes no behaviour on the deployed
--    database; every statement below reproduces a policy that is already there,
--    verbatim. Reconciliation and redesign are two jobs, and doing them in one
--    file makes it impossible to tell which change caused what.
--
-- ⚠️ `*_insert WITH CHECK (true)` IS DELIBERATELY COPIED AS-IS, including its
--    weakness. It mirrors the parent tables' `reqlog_insert` and `audit_insert`,
--    which finding B15 records as forgeable — the operational log the admin
--    panel reads can be written by any bound user. **Phase 2 tightens the parent
--    and these partitions together.** Tightening only the partitions here would
--    leave the parent open and the two disagreeing, which is how this class of
--    problem started.
--
-- The audit log is append-only by design, so there is no DELETE or UPDATE policy
-- on either partition, matching the parents.
--
-- Idempotent: the Supabase CLI does not wrap a file in a transaction, so every
-- statement must be safe to re-run.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- audit_log_default
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS audit_default_admin_read ON public.audit_log_default;
CREATE POLICY audit_default_admin_read ON public.audit_log_default
  FOR SELECT TO app_backend
  USING (app.is_admin());

DROP POLICY IF EXISTS audit_default_insert ON public.audit_log_default;
CREATE POLICY audit_default_insert ON public.audit_log_default
  FOR INSERT TO app_backend
  WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- api_request_log_default
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS reqlog_default_admin_read ON public.api_request_log_default;
CREATE POLICY reqlog_default_admin_read ON public.api_request_log_default
  FOR SELECT TO app_backend
  USING (app.is_admin());

DROP POLICY IF EXISTS reqlog_default_insert ON public.api_request_log_default;
CREATE POLICY reqlog_default_insert ON public.api_request_log_default
  FOR INSERT TO app_backend
  WITH CHECK (true);

COMMENT ON POLICY audit_default_admin_read ON public.audit_log_default IS
  'Mirrors audit_admin_read on the parent. Recorded by migration 20260816130000 '
  'after it was found live and undocumented (finding F1).';
COMMENT ON POLICY audit_default_insert ON public.audit_log_default IS
  'Mirrors audit_insert on the parent, including its WITH CHECK (true) — see '
  'finding B15. Phase 2 tightens parent and partition together.';
COMMENT ON POLICY reqlog_default_admin_read ON public.api_request_log_default IS
  'Mirrors reqlog_admin_read on the parent. Recorded by migration 20260816130000 '
  'after it was found live and undocumented (finding F1).';
COMMENT ON POLICY reqlog_default_insert ON public.api_request_log_default IS
  'Mirrors reqlog_insert on the parent, including its WITH CHECK (true) — see '
  'finding B15. Phase 2 tightens parent and partition together.';
