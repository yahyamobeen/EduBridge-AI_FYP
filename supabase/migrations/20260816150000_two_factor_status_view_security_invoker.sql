-- ============================================================================
-- EduBridge AI — two_factor_status_v runs as its CALLER (finding B1)
--
-- WHAT WAS WRONG. `two_factor_status_v` (20260801120000:236) reads
-- `two_factor_enrollment` and counts rows in `two_factor_backup_code`. Both
-- tables have row-level security enabled, forced, and an owner-scoped policy —
-- and none of that applied to anyone querying the view, for three reasons that
-- had to line up:
--
--   1. A VIEW HAS NO ROW-LEVEL SECURITY OF ITS OWN. Policies attach to tables.
--   2. Without `security_invoker`, a view executes as its OWNER, so the
--      policies on the tables underneath are evaluated as the owner — who
--      satisfies none of them and is exempt from all of them.
--   3. `GRANT … ON ALL TABLES IN SCHEMA public` (20260801120100:36) **includes
--      views**. `app_backend` was therefore granted SELECT on it.
--
-- Net effect: one SELECT returned every account's two-factor method, status,
-- lockout expiry, failed-attempt count and remaining backup-code count.
--
-- ⚠️ It also explains why the enable-and-force loop never caught this. That
--    loop (20260801120100:126-137) iterates `pg_tables`, which lists tables and
--    not views, so the view was invisible to the very pass that was supposed to
--    protect everything. That asymmetry — grants that are forward-looking
--    against protection that was a one-shot loop — is finding B19, and §2.6
--    adds the test that stops it regrowing.
--
-- NOT REACHABLE TODAY. `grep -rn "two_factor_status_v"` finds no Python, no
-- route and no ORM model — only two migrations, `supabase/README.md` and the
-- architecture documents. This is the second layer, and the point of a second
-- layer is that it holds when the first has a bug.
--
-- ⚠️ WHAT THIS CHANGES, STATED PLAINLY: both underlying tables are owner-scoped,
--    so with `security_invoker` on, THE VIEW NOW RETURNS ONLY THE CALLER'S OWN
--    ROW. It is no longer the cross-account "admin support view" that
--    `database.md` described it as, and that wording is corrected in the same
--    change. Keeping it is deliberate: the alternative considered and rejected
--    was to add `FOR SELECT … USING (app.is_admin())` policies to both tables,
--    which would have restored cross-account visibility by granting
--    administrators a NEW power over everyone's security posture. That is a
--    product decision, not a bug fix, and `user-stories.md:294` already lists an
--    administrator touching a second factor without identity checks as a failure
--    criterion. `GET /api/auth/2fa/status` (phase 3.3) is the specified way to
--    expose this data.
--
-- Verified from the catalogue before writing, not assumed: `reloptions` was
-- NULL, `relrowsecurity` false, policy count zero.
--
-- Idempotent: `SET` on a view option is a no-op when the value already matches,
-- and the Supabase CLI does not wrap a file in a transaction.
-- ============================================================================

-- BEFORE: reloptions = NULL  → runs as owner, bypasses both tables' policies
ALTER VIEW public.two_factor_status_v SET (security_invoker = true);
-- AFTER:  reloptions = {security_invoker=true} → runs as caller, policies apply

COMMENT ON VIEW public.two_factor_status_v IS
  'Two-factor status for THE CALLING USER ONLY. Carries no secret and no code '
  'hash. `security_invoker=true` (20260816150000, finding B1) makes it execute '
  'as the caller, so `two_factor_enrollment_owner` and '
  '`two_factor_backup_code_owner` apply — without it the view ran as its owner '
  'and exposed every account. It is NOT an administrator view: both underlying '
  'policies are owner-scoped, so an administrator sees only their own row. '
  'Cross-account 2FA state belongs to GET /api/auth/2fa/status, not here.';
