-- ============================================================================
-- EduBridge AI — block administrator self-registration (finding A1)
--
-- `POST /api/auth/register` accepted `role: admin` and wrote it straight
-- through. The student validators return early for a non-student, the role
-- chain in `register()` has no `else`, and `derive_onboarding_state` skips both
-- the guardian and the subscription rules for a non-student — so an admin
-- account reached `active` in one unauthenticated request, and `app.is_admin()`
-- then opened `app_user_self_read`, `audit_admin_read`, `subscription_admin_read`,
-- `sbom_admin_read`, `vetting_admin_read` and `reqlog_admin_read`.
--
-- The application layer is fixed separately: `RegisterRequest.role` is now
-- `RegistrableRole`, which has three members. This file is the SECOND layer.
-- Neither is sufficient alone — a validator can be forgotten by a future
-- endpoint, and a policy cannot produce a readable error message.
--
-- ⚠️ NOT A NEW POLICY. `app_user_insert` was already reconciled to the
--    owner-scoped form by 20260802150000. This adds one conjunct to it. The
--    original `WITH CHECK (true)` in 20260801120100 has not been live since
--    then, whatever any stale comment says.
--
-- ⚠️ SCOPE OF THE RESTRICTION: `TO app_backend`. It constrains the application
--    role only. The repository owner, connecting as the table owner, is
--    unaffected — which is deliberate, because promoting a user to
--    administrator is an owner-run SQL operation and must remain possible.
--
-- ⚠️ NO MIGRATION SEEDS AN ADMINISTRATOR, so before applying this, audit for
--    rows that should not exist. The query is in the phase handoff; briefly:
--        SELECT id, email, created_at FROM public.app_user WHERE role = 'admin';
--    Any row returned was created through the hole this closes.
--
-- Idempotent: the Supabase CLI does not wrap a file in a transaction, so every
-- statement must be safe to re-run.
-- ============================================================================

DROP POLICY IF EXISTS app_user_insert ON public.app_user;

CREATE POLICY app_user_insert ON public.app_user
  FOR INSERT TO app_backend
  WITH CHECK (id = app.current_user_id() AND role <> 'admin');

COMMENT ON POLICY app_user_insert ON public.app_user IS
  'Registration inserts its own row only, and never as an administrator. '
  'The id clause is fail-closed: a forgotten set_current_user_id() makes the '
  'INSERT fail loudly rather than silently create a user nobody can read back. '
  'The role clause is finding A1 — admin is not self-registrable. Promoting a '
  'user to admin is an owner-run operation and is not subject to this policy.';
