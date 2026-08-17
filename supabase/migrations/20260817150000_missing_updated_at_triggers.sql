-- ============================================================================
-- EduBridge AI — the `updated_at` columns nothing maintains (Phase 5, D14)
--
-- `app.set_updated_at()` exists and nine tables use it. Four carry an
-- `updated_at` column and have NO trigger at all, so the value is written once
-- by its `DEFAULT now()` and then never changes again. The column does not
-- report when the row was last modified; it reports when it was created, while
-- looking exactly like the other nine.
--
-- ⚠️ THE PLAN NAMED THREE. THE LIVE CATALOGUE HAS FOUR.
--    The register listed `teacher_profile`, `parent_profile` and
--    `admin_profile` — the three that are visibly adjacent in
--    `initial_schema.sql`. Querying `pg_class`/`pg_trigger` instead of reading
--    the file adds **`mastery_estimate`**, which is declared 400 lines away.
--    That is finding F1's lesson again: author from the catalogue, never from
--    the migration files. The query:
--
--      SELECT c.relname,
--             EXISTS (SELECT 1 FROM pg_trigger t
--                      WHERE t.tgrelid = c.oid AND NOT t.tgisinternal)
--        FROM pg_class c
--        JOIN pg_namespace n ON n.oid = c.relnamespace
--        JOIN pg_attribute a ON a.attrelid = c.oid
--                           AND a.attname = 'updated_at' AND NOT a.attisdropped
--       WHERE n.nspname = 'public' AND c.relkind = 'r';
--      -- 13 tables with the column, 4 without a trigger
--
-- WHY IT MATTERS DIFFERENTLY PER TABLE:
--
--   * `teacher_profile` — `institution` is editable, so a stale `updated_at`
--     is a lie about data that genuinely changes.
--   * `parent_profile`, `admin_profile` — nothing writes them today, so this is
--     purely forward-looking. That is the point: the trigger has to exist
--     BEFORE the first writer, or the first writer is the bug report.
--   * `mastery_estimate` — ⚠️ the one with teeth. It is one of the five
--     progress tables `20260816170000` made read-only (finding B7), and its
--     numbers are what a parent and a teacher read. When the endpoint that
--     writes it is built, "when was this last recalculated" is exactly the
--     question `updated_at` is there to answer, and a column frozen at insert
--     time would answer it wrongly and plausibly.
--
-- ⚠️ `app.set_updated_at()` HAD ITS `PUBLIC` EXECUTE REVOKED BY `20260816190000`
--    (finding C5) and is granted only to `app_backend`. PostgreSQL checks
--    `EXECUTE` on a trigger function WHEN THE TRIGGER IS CREATED, not when it
--    fires — so these statements must run as a role that can execute it. The
--    owner can, and migrations run as the owner, so this works; it would NOT
--    work from an `app_backend` session, which is worth knowing before someone
--    tries to apply it that way.
--
-- ⚠️ THE TRIGGER FUNCTION USES `now()`, AND THAT IS CORRECT HERE — unlike
--    everything in Phase 4. `updated_at` records which TRANSACTION last touched
--    the row, so every row written by one transaction sharing a timestamp is
--    the desired behaviour, not a bug. `clock_timestamp()` would make two rows
--    updated by the same statement disagree.
--
-- ⚠️ NO COLUMN GRANT IS NEEDED, and this is the same measurement
--    `20260816160000` recorded: PostgreSQL checks column privileges against the
--    columns named in the STATEMENT, not against columns a trigger assigns to
--    NEW. `test_column_grants.py::test_the_updated_at_trigger_still_fires_without_a_grant_on_it`
--    pins that for `app_user`; the same reasoning covers these four.
--
-- Idempotent: `DROP TRIGGER IF EXISTS` before each `CREATE TRIGGER`, because
-- `CREATE TRIGGER` has no `IF NOT EXISTS` and `CREATE OR REPLACE TRIGGER` is
-- PostgreSQL 14+. The drop-then-create form works everywhere and re-running is
-- a no-op.
-- ============================================================================

DROP TRIGGER IF EXISTS trg_teacher_profile_updated ON public.teacher_profile;
CREATE TRIGGER trg_teacher_profile_updated
  BEFORE UPDATE ON public.teacher_profile
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

DROP TRIGGER IF EXISTS trg_parent_profile_updated ON public.parent_profile;
CREATE TRIGGER trg_parent_profile_updated
  BEFORE UPDATE ON public.parent_profile
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

DROP TRIGGER IF EXISTS trg_admin_profile_updated ON public.admin_profile;
CREATE TRIGGER trg_admin_profile_updated
  BEFORE UPDATE ON public.admin_profile
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

-- The one the register missed.
DROP TRIGGER IF EXISTS trg_mastery_estimate_updated ON public.mastery_estimate;
CREATE TRIGGER trg_mastery_estimate_updated
  BEFORE UPDATE ON public.mastery_estimate
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
