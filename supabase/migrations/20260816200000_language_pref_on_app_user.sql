-- ============================================================================
-- EduBridge AI — `language_pref` moves to `app_user` (Phase 3, FR-A8)
--
-- WHY THIS EXISTS. `PATCH /api/auth/me` (tdd.md:193) must update "own profile
-- and stored language_pref, which governs outgoing email", and FR-A8
-- (prd.md:235, prd.md:450 — "Role: all") grants account management to ALL FOUR
-- roles. `language_pref` lives on `student_profile` (20260801120000:120), a
-- table teachers, parents and administrators do not have a row in.
--
-- ⚠️ THE CONSEQUENCE, READ OFF THE CODE RATHER THAN ASSUMED.
--    `app.lookup_user_for_email_flow` LEFT JOINs `student_profile`
--    (20260803160000:143-147), so `language_pref` comes back NULL for three
--    roles out of four and `_locale_of` (service.py:676-678) falls back to
--    'en'. **A TEACHER CAN NEVER RECEIVE URDU EMAIL**, and no endpoint work
--    fixes it, because there is nowhere to store the answer.
--    `20260803160000:127-128` states the LEFT JOIN as a fact without drawing
--    this conclusion, and `service.py:195-197` complains about the same gap at
--    registration time ("`student_profile` is the only place it is stored, so a
--    teacher or parent has none at all"). This is that complaint, fixed.
--
-- ⚠️ SOURCE OF TRUTH, DECIDED AND WRITTEN DOWN SO THE TWO CANNOT DRIFT.
--    After this migration `app_user.language_pref` is the ONLY copy anything
--    reads — outgoing email AND `MeResponse.profile.language_pref`, which
--    `_ME_QUERY` is changed in the same commit to source from `u`, not `sp`.
--    The published response shape does not change.
--
--    `student_profile.language_pref` IS DELIBERATELY KEPT AND IS NO LONGER
--    READ BY ANYTHING. Dropping it would take `20260816160000`'s
--    `GRANT UPDATE (language_pref) ON student_profile` with it, leaving that
--    table with zero updatable columns and deleting a passing authorization
--    test for no gain. Registration keeps writing it with the same value it
--    writes to `app_user`, so the two agree at creation; only `app_user` is
--    ever updated afterwards. If you are reading `sp.language_pref` anywhere,
--    that is the bug.
--
-- ⚠️ COLUMN GRANTS DO NOT FOLLOW A NEW COLUMN THE WAY YOU WANT.
--    `20260816160000` revoked table-wide UPDATE on `app_user` and granted
--    `full_name` ONLY. A column added afterwards is therefore NOT updatable by
--    `app_backend`, so the GRANT below is load-bearing — without it
--    `PATCH /auth/me` fails with `permission denied for column language_pref`.
--    SELECT and INSERT were never revoked and remain table-wide, which is why
--    registration can write the new column without a second grant.
--
-- ⚠️ `test_column_grants.py::test_only_the_intended_columns_carry_their_own_grant`
--    ASSERTS THE WHOLE ACL SET AND WILL FAIL UNTIL ITS EXPECTED LIST GAINS
--    `('app_user', 'language_pref', 'UPDATE')`. That is the guard working, and
--    it is the third time it has caught a later change (§2.2 -> §2.3 was the
--    first two). Run it BEFORE updating the list and confirm it names the new
--    column; a test updated in advance of the change it is meant to catch has
--    proved nothing.
--
-- CALL SITES WALKED BEFORE CHANGING THE FUNCTION (caller-and-callee rule):
--   * `app.lookup_user_for_email_flow` has exactly ONE caller,
--     `_lookup_for_email_flow` (service.py:650-673), reached from
--     `forgot_password` (:1225) and `resend_email_verification` (:1199). Both
--     read `language_pref` only through `_locale_of`.
--   * `student_profile.language_pref` is read by `_ME_QUERY` (service.py:455,
--     surfaced at :569) and written by `register` (service.py:161). Nothing
--     else in `backend/app/` mentions it.
--
-- ⚠️ THE RETURN TYPE OF `lookup_user_for_email_flow` IS UNCHANGED, so this is a
--    `CREATE OR REPLACE` and NOT a drop. That matters: a DROP would take the
--    `REVOKE ... FROM PUBLIC`, the `GRANT` and the `COMMENT` with it and
--    silently reopen finding C5 (see 20260816140000, where it did). The
--    permissions block at the foot re-states them anyway, because a migration
--    that is correct only because of what it did NOT do is fragile.
--
-- Idempotent: `ADD COLUMN IF NOT EXISTS`, a guarded backfill, a `GRANT` of a
-- privilege already held and `CREATE OR REPLACE` are all no-ops on re-run.
-- ============================================================================

-- ── 1 + 2. The column, and the one-time backfill that must accompany it ─────
--
-- NOT NULL DEFAULT 'en' mirrors `student_profile.language_pref`
-- (20260801120000:120) exactly, so the two columns cannot disagree about what
-- "unset" means. `language_code` is ('en','ur','roman_ur').
--
-- ⚠️ THE BACKFILL IS GATED ON THE COLUMN NOT ALREADY EXISTING, AND THE OBVIOUS
--    ALTERNATIVE IS WRONG. `ADD COLUMN IF NOT EXISTS` followed by a guarded
--    `UPDATE ... WHERE u.language_pref = 'en' AND sp.language_pref <> 'en'`
--    looks idempotent and is not:
--
--      a student registers with 'ur'      -> sp='ur', u backfilled to 'ur'
--      they choose English in settings    -> u='en', sp still 'ur'
--      this file is applied a second time -> the guard MATCHES, and their
--                                            deliberate choice is reverted
--
--    The guard protects a change away from English and silently undoes a change
--    TO English — an idempotent STATEMENT that is not an idempotent MIGRATION.
--    Binding the backfill to the moment the column is created is the only form
--    that cannot fire twice, because that moment happens exactly once.
DO $migration$
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_attribute
     WHERE attrelid = 'public.app_user'::regclass
       AND attname  = 'language_pref'
       AND NOT attisdropped
  ) THEN
    ALTER TABLE public.app_user
      ADD COLUMN language_pref language_code NOT NULL DEFAULT 'en';

    -- Runs in the same execution that created the column, and never again.
    UPDATE public.app_user u
       SET language_pref = sp.language_pref
      FROM public.student_profile sp
     WHERE sp.user_id       = u.id
       AND sp.language_pref <> 'en';
  END IF;
END
$migration$;

-- ── 3. The grant ────────────────────────────────────────────────────────────
-- The second column a user may edit about themselves, alongside `full_name`.
-- Everything else on `app_user` — `role`, `status`, `email_verified_at`,
-- `password_hash` — stays unwritable, which is findings B2 and B3.
GRANT UPDATE (language_pref) ON public.app_user TO app_backend;

-- ── 4. The email-flow lookup reads the new column ───────────────────────────
-- Same signature, same return type: `CREATE OR REPLACE`, no DROP. The only
-- change is `sp.language_pref` -> `u.language_pref` and the loss of the LEFT
-- JOIN that made it NULL for non-students.
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
  SELECT u.id, u.email, u.full_name, u.language_pref, u.email_verified_at, u.status
  FROM public.app_user u
  WHERE lower(u.email) = lower(p_email)
    AND u.deleted_at IS NULL;
$$;

-- ============================================================================
-- Permissions. Re-stated rather than relied upon: `CREATE OR REPLACE` keeps
-- them, but the next person to change this function may need a DROP, and
-- finding C5 says a function left executable by PUBLIC is how that goes wrong.
-- ============================================================================
REVOKE ALL   ON FUNCTION app.lookup_user_for_email_flow(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.lookup_user_for_email_flow(text) TO app_backend;

COMMENT ON FUNCTION app.lookup_user_for_email_flow(text) IS
  'POST /api/auth/password/forgot and /email/resend. Returns the stored address '
  'and language_pref for locale-correct delivery. language_pref comes from '
  'app_user as of 20260816200000 -- it was student_profile, which meant every '
  'teacher, parent and administrator silently received English.';

COMMENT ON COLUMN public.app_user.language_pref IS
  'Stored language preference for OUTGOING EMAIL and for MeResponse.profile. '
  'The single source of truth since 20260816200000; student_profile.language_pref '
  'is kept for its column grant and is read by nothing. Distinct from the '
  'interface locale, which is a URL segment on the frontend.';
