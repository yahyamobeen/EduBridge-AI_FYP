-- ============================================================================
-- EduBridge AI — helper functions stop being executable by PUBLIC (finding C5)
--
-- PostgreSQL grants `EXECUTE` on a new function to `PUBLIC` by default. Every
-- other privileged function in this project revokes it explicitly; these did
-- not, so they carry the default to this day:
--
--     app.current_user_id()                     -- reads the bound session user
--     app.is_admin()                            -- the predicate in 8 policies
--     app.is_enrolled_in(uuid)
--     app.is_verified_guardian_of(uuid)
--     app.owns_space(uuid)
--     app.teaches_student_subject(uuid, uuid)
--     app.set_updated_at()                      -- trigger function
--
-- ⚠️ THE PLAN SAYS FIVE. THE CATALOGUE SAYS SEVEN. Counted from
--    `aclexplode(proacl)`, not from the migration files. `set_updated_at` and
--    one other were missed when the finding was first written.
--
-- ⚠️ UNREACHABLE TODAY ONLY BECAUSE OF A SECOND, UNRELATED GRANT. `USAGE` on
--    schema `app` is granted narrowly, and without schema usage a PUBLIC
--    EXECUTE cannot be exercised. That is one `GRANT USAGE ON SCHEMA app` away
--    from being false, and nothing records the dependency — which is exactly
--    the shape of finding B19: a protection that holds by accident of a
--    neighbouring decision rather than by its own statement.
--
-- WHAT THESE WOULD LEAK IF REACHED: `app.is_verified_guardian_of(uuid)` and
-- `app.teaches_student_subject(uuid, uuid)` answer questions about OTHER
-- people's relationships, and `app.current_user_id()` reveals the bound session
-- identity. None mutates anything.
--
-- ⚠️ THE TRIGGER FUNCTION IS THE ONE THAT COULD BREAK EVERY UPDATE IN THE APP,
--    and it is the reason `app_backend` is granted explicitly below rather than
--    the privilege simply being revoked. PostgreSQL checks `EXECUTE` on a
--    trigger function when the TRIGGER IS CREATED, not each time it fires — so a
--    bare revoke would probably be harmless. "Probably" is not the standard for
--    a function attached to seven tables' `updated_at`, so the grant makes it
--    moot in both directions, and `test_column_grants.py` already exercises the
--    trigger through a real UPDATE as `app_backend`.
--
-- `app_backend` is granted rather than left to inherit, because policy
-- expressions are evaluated with the privileges of the role RUNNING THE QUERY.
-- `app.is_admin()` appears in eight policies; without EXECUTE, every one of them
-- would error rather than deny — and an erroring policy is a broken application,
-- not a secure one.
--
-- Idempotent: REVOKE of an absent privilege and GRANT of a held one are no-ops.
-- ============================================================================

REVOKE ALL ON FUNCTION app.current_user_id()                        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.is_admin()                               FROM PUBLIC;
REVOKE ALL ON FUNCTION app.is_enrolled_in(uuid)                     FROM PUBLIC;
REVOKE ALL ON FUNCTION app.is_verified_guardian_of(uuid)            FROM PUBLIC;
REVOKE ALL ON FUNCTION app.owns_space(uuid)                         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.teaches_student_subject(uuid, uuid)      FROM PUBLIC;
REVOKE ALL ON FUNCTION app.set_updated_at()                         FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app.current_user_id()                     TO app_backend;
GRANT EXECUTE ON FUNCTION app.is_admin()                            TO app_backend;
GRANT EXECUTE ON FUNCTION app.is_enrolled_in(uuid)                  TO app_backend;
GRANT EXECUTE ON FUNCTION app.is_verified_guardian_of(uuid)         TO app_backend;
GRANT EXECUTE ON FUNCTION app.owns_space(uuid)                      TO app_backend;
GRANT EXECUTE ON FUNCTION app.teaches_student_subject(uuid, uuid)   TO app_backend;
GRANT EXECUTE ON FUNCTION app.set_updated_at()                      TO app_backend;
