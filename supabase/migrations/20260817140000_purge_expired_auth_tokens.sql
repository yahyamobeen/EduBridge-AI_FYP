-- ============================================================================
-- EduBridge AI — auth_token retention (Phase 4, §4.5)
--
-- THERE IS NO PURGE ANYWHERE. Verified: no cron, no scheduler, no worker in
-- `backend/app/` and nothing in `render.yaml`. Every token this system has ever
-- issued is still in the table, and the table only grows.
--
-- MEASURED ON THE LIVE PROJECT (2026-08-17): 165 rows, of which 118 are revoked
-- and **0 are older than the grace period below**. So this is preventative, not
-- remedial — which is the right time to add it, because the growth rate is
-- roughly 40 rows per active user per day once refresh rotation is in normal
-- use, and a table nobody prunes is discovered when it is already large.
--
-- ⚠️ THE 30-DAY GRACE IS THE WHOLE DESIGN, AND DELETING ON EXPIRY ALONE WOULD
--    QUIETLY BREAK REUSE DETECTION.
--
--    `app.rotate_refresh_token` checks `revoked` BEFORE `expires_at`, on
--    purpose: a stolen token replayed after it expired should still be reported
--    as theft and still revoke the family. That only works while the ROW SURVIVES.
--    Delete it and the same replay becomes `not_found` — an ordinary 401, no
--    family revocation, no audit row. The attack stops being visible rather than
--    stops working, which is the worse of the two outcomes and the harder one to
--    notice.
--
--    So rows are kept for `p_grace` PAST EXPIRY, not past issuance.
--
-- ⚠️ DELETE ON `auth_token` WAS REVOKED FROM `app_backend` BY `20260816170000`
--    (finding B6), and this function does not change that. It is SECURITY
--    DEFINER, so it executes as the owner; the application role still cannot
--    delete a token, which is what stops a caller erasing the evidence of their
--    own revocation.
--
-- ⚠️ `clock_timestamp()`, NOT `now()` — the standing Phase 4 rule. A purge run
--    inside a long transaction would otherwise measure the grace period from the
--    transaction's start rather than from the moment the row is examined.
--
-- Idempotent: `CREATE OR REPLACE`, and the scheduling block below re-registers
-- rather than duplicating.
-- ============================================================================

CREATE OR REPLACE FUNCTION app.purge_expired_auth_tokens(p_grace interval DEFAULT '30 days')
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_deleted integer;
BEGIN
  DELETE FROM public.auth_token
   WHERE expires_at < clock_timestamp() - p_grace;
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END;
$$;

-- ⚠️ NOT GRANTED TO `app_backend`, for the same reason `app.invalidate_sessions`
--    is not: no request path should be able to delete audit-relevant rows, and a
--    grant here would let any authenticated caller run a bulk DELETE. It is a
--    maintenance job, so the owner and the scheduler are the only callers.
REVOKE ALL ON FUNCTION app.purge_expired_auth_tokens(interval) FROM PUBLIC;

COMMENT ON FUNCTION app.purge_expired_auth_tokens(interval) IS
  'Deletes auth_token rows more than p_grace PAST EXPIRY (default 30 days). The '
  'grace is not tidiness: rotate_refresh_token checks `revoked` before '
  '`expires_at`, so a stolen token replayed after expiry is still reported as '
  'theft -- but only while its row exists. Deleting on expiry alone turns that '
  'replay into a silent 401. Never granted to app_backend.';


-- ── Scheduling ──────────────────────────────────────────────────────────────
-- ⚠️ `pg_cron` IS AVAILABLE ON THIS PROJECT BUT NOT INSTALLED (measured
--    2026-08-17: `pg_available_extensions` yes, `pg_extension` no). Enabling an
--    extension is a different kind of decision from adding a function, and it is
--    the repository owner's to make -- so this migration does NOT create it.
--
--    The block below schedules the job IF pg_cron is present and does nothing if
--    it is not, so:
--      * applying now installs the function and skips the schedule;
--      * enabling pg_cron later and re-running this file schedules it, with no
--        other change and no duplicate job.
--
--    To enable: Supabase Dashboard -> Database -> Extensions -> `pg_cron`, then
--    re-apply this file. Until then the function exists and can be run by hand:
--        SELECT app.purge_expired_auth_tokens();
--
-- 03:17 daily rather than on the hour: nothing else competes for that minute,
-- and a purge is not time-critical.
DO $schedule$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    -- Unschedule first. Older pg_cron versions do not upsert by name, so
    -- re-running this file would otherwise accumulate duplicate jobs that all
    -- fire together.
    IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'purge-expired-auth-tokens') THEN
      PERFORM cron.unschedule('purge-expired-auth-tokens');
    END IF;

    PERFORM cron.schedule(
      'purge-expired-auth-tokens',
      '17 3 * * *',
      'SELECT app.purge_expired_auth_tokens()'
    );
    RAISE NOTICE 'scheduled purge-expired-auth-tokens (daily 03:17)';
  ELSE
    RAISE NOTICE
      'pg_cron is not installed -- app.purge_expired_auth_tokens() created but NOT scheduled. '
      'Enable pg_cron and re-apply this file, or run the function from an external scheduler.';
  END IF;
END
$schedule$;
