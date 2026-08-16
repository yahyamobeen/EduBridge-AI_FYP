-- ============================================================================
-- EduBridge AI — session policy columns (Phase 4, findings E2 and part of E3)
--
-- THREE COLUMNS THAT DO NOT EXIST, verified from `models/identity.py` and from
-- every migration in this directory:
--
--   app_user.sessions_invalidated_at  — the moment every session before it dies
--   auth_token.family_started_at      — when this rotating chain BEGAN
--   auth_token.revoked_reason         — why a token stopped being usable
--
-- WHAT THEY BUY, STATED PLAINLY.
--
-- 1. `sessions_invalidated_at` closes the window an access token leaves open.
--    Revoking refresh tokens ends the ability to get a NEW access token; it does
--    nothing about the one already in the caller's memory, which stays valid for
--    up to `access_token_ttl_minutes`. So today a password change — the thing a
--    user does when they believe they have been compromised — leaves the
--    attacker signed in for another quarter of an hour. `20260816210000` says
--    exactly this in its own comments and deliberately did not smuggle the fix
--    in; this is that fix.
--
-- 2. `family_started_at` gives refresh rotation an ABSOLUTE ceiling. Rotation
--    currently means a chain can be extended for ever, seven days at a time, so
--    "the session expires" is not true of any session anybody keeps using.
--
-- 3. `revoked_reason` makes "why is this token dead" answerable. Logout, reuse
--    detection, password change and password reset are four very different
--    events that are today one indistinguishable `revoked = true`.
--
-- ⚠️ THE BACKFILL GUARD HERE IS A VALUE GUARD, AND IN 20260816200000 THAT WAS
--    THE WRONG SHAPE. Worth stating why the two differ, because copying the
--    wrong one is easy.
--
--    That migration guarded on `u.language_pref = 'en'`, a value a USER can
--    legitimately choose — so a second run reverted anybody who had chosen it,
--    and the gate had to be moved onto the column's creation instead.
--
--    `family_started_at IS NULL` is not that. NULL is not a value anything
--    chooses; it is the absence of one, and after this migration every writer
--    supplies it. So the guard can only ever fill a hole, never overwrite an
--    answer, and re-running is genuinely a no-op AND a repair. Idempotent as a
--    statement and as a migration.
--
-- ⚠️ COLUMN GRANTS: `auth_token` IS NARROWED HERE, AND THAT IS NOT INCIDENTAL.
--    §2.3 (`20260816170000`, finding B6) split this table's `FOR ALL` policy
--    into `FOR SELECT` plus `FOR UPDATE ... WITH CHECK (revoked = true)` — a
--    one-way door. The UPDATE GRANT, however, stayed table-wide, so the moment
--    these columns exist `app_backend` can write them: a caller could revoke
--    their own token AND author its `revoked_reason`, or rewrite
--    `family_started_at` and defeat the absolute cap this migration exists to
--    create. The policy permits it, because the row is theirs and `revoked` is
--    becoming true.
--
--    So UPDATE narrows to `revoked` — the one column the application writes
--    directly. Everything else on this table is written by SECURITY DEFINER
--    functions, which grants do not constrain.
--
-- CALL SITES WALKED BEFORE REVOKING (caller-and-callee rule):
--   * `revoke_user_tokens` (`tokens.py:150`) — the ONLY plain UPDATE against
--     `auth_token` in `backend/app/`. It is `update(AuthToken).values(revoked=True)`
--     and names no other column, so `GRANT UPDATE (revoked)` keeps logout working
--     unchanged. Its one caller is `logout` (`service.py:454`).
--   * `app.revoke_auth_token`, `app.revoke_refresh_family` and
--     `app.consume_password_reset_token` also UPDATE the table and are all
--     SECURITY DEFINER, so they execute as the owner and are unaffected.
--   * INSERT and DELETE were already revoked by `20260816170000`; nothing here
--     changes that.
--
-- ⚠️ CONSEQUENCE, RECORDED RATHER THAN SILENTLY ACCEPTED: an ordinary logout
--    leaves `revoked_reason` NULL, because `revoke_user_tokens` may no longer
--    write it. **NULL therefore MEANS "ordinary logout"** and is the most
--    common value in the column. Giving logout a real reason means moving it
--    into a SECURITY DEFINER function too; that is a deliberate follow-up, not
--    an oversight, and it is written down in the deferred log.
--
-- ⚠️ `test_column_grants.py::test_only_the_intended_columns_carry_their_own_grant`
--    ASSERTS THE WHOLE ACL SET and will fail on `('auth_token','revoked','UPDATE')`
--    until its list is updated. Run it BEFORE updating and confirm it names that
--    column; this is the fifth change that guard has caught.
--
-- `auth_token` is NOT partitioned (only `audit_log` and `api_request_log` are),
-- so all three `ALTER TABLE ... ADD COLUMN` statements are metadata-only and do
-- not rewrite the table.
--
-- Idempotent: `ADD COLUMN IF NOT EXISTS`, a NULL-guarded backfill, and REVOKE /
-- GRANT of privileges already in force are all no-ops on re-run.
-- ============================================================================

-- ── 1. The columns ──────────────────────────────────────────────────────────
-- Nullable on purpose. `sessions_invalidated_at` is NULL for a user who has
-- never had an invalidation event, which is most of them.
--
-- ⚠️ THAT NULL IS A TRAP FOR THE PYTHON SIDE. The comparison must NOT go in a
--    WHERE clause: comparing a token's issue time against NULL yields NULL, the
--    row is filtered out, the caller reads "no such user" and **every request
--    401s for everybody** — with the same message as a bad token, so it looks
--    like a client bug. Select the column and compare in Python.
ALTER TABLE public.app_user
  ADD COLUMN IF NOT EXISTS sessions_invalidated_at timestamptz;

ALTER TABLE public.auth_token
  ADD COLUMN IF NOT EXISTS family_started_at timestamptz;

ALTER TABLE public.auth_token
  ADD COLUMN IF NOT EXISTS revoked_reason text;

-- ⚠️ `revoked_at` EXISTS FOR ONE REASON: TELLING A RACE FROM A THEFT.
--    Rotation means a refresh token is valid exactly once, so a second use is
--    read as theft and the whole family is revoked. That is right for a thief
--    and wrong for a user with two browser tabs — the client's single-flight
--    guard is PER TAB, so two tabs refreshing together present the same token
--    twice, and today the loser signs the user out of every device while the
--    audit trail records a security incident that did not happen.
--
--    A row lock alone does not fix this. It stops the family FORKING, which is
--    the more serious half, but the loser still finds `revoked = true`.
--    Distinguishing the two needs to know WHEN the revocation happened, which
--    is what this column records — and the distinction is safe because a replay
--    is only forgiven while a live sibling of the same family still exists and
--    the revocation is seconds old. A thief replaying a captured token later
--    trips full reuse detection exactly as before.
--
--    The loser's clean 401 is recoverable on its own: the winner's response
--    already overwrote the httpOnly cookie, so the retry uses the new token.
ALTER TABLE public.auth_token
  ADD COLUMN IF NOT EXISTS revoked_at timestamptz;

COMMENT ON COLUMN public.app_user.sessions_invalidated_at IS
  'Every access token issued at or before this instant is refused. Stamped with '
  'clock_timestamp(), NEVER now(): now() is transaction_timestamp() and is frozen '
  'for the whole transaction, so a token minted in the same transaction as the '
  'stamp would survive it. NULL means no invalidation event has ever occurred.';

COMMENT ON COLUMN public.auth_token.family_started_at IS
  'When this rotating refresh chain began. Carried forward unchanged across every '
  'rotation, so it bounds the chain absolutely rather than per-token. NULL on the '
  'five non-refresh kinds, which do not rotate.';

COMMENT ON COLUMN public.auth_token.revoked_at IS
  'When the token was revoked, used to tell a two-tab rotation RACE from a token '
  'THEFT: a replay within the grace window, while a live sibling of the same '
  'family exists, is a race and gets a plain 401 rather than revoking the family. '
  'NULL on every live token and on rows revoked before 20260817120000.';

COMMENT ON COLUMN public.auth_token.revoked_reason IS
  'Why the token stopped being usable: reuse_detected, password_change, '
  'password_reset, session_invalidated. NULL means an ordinary logout, which is '
  'the common case -- see 20260817120000 for why logout does not write it.';

-- ── 2. Backfill the chains already in flight ────────────────────────────────
-- Without this every live refresh token has a NULL family start, and the cap
-- check has to treat NULL as "unbounded" for ever. `created_at` is the honest
-- answer for a chain whose real origin was not recorded: it is the earliest
-- moment we can prove this particular token existed.
UPDATE public.auth_token
   SET family_started_at = created_at
 WHERE kind              = 'refresh'
   AND revoked           = false
   AND family_started_at IS NULL;

-- ── 3. Narrow the write surface ─────────────────────────────────────────────
-- BEFORE: UPDATE on every column, so a caller could author `revoked_reason` on
--         their own revocation and rewrite `family_started_at` to reset the cap.
REVOKE UPDATE ON public.auth_token FROM app_backend;
-- AFTER:  the one column `revoke_user_tokens` names. Everything else is written
--         by SECURITY DEFINER functions, which this does not constrain.
GRANT UPDATE (revoked) ON public.auth_token TO app_backend;
