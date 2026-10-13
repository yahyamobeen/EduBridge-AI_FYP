-- ============================================================================
-- EduBridge AI — classroom space functions
--
-- 20261004120000 removed every direct write path on `enrollment` and
-- `join_code`, and INSERT on `classroom_space`. These functions are now the
-- only writers, and each derives the ACTOR from app.current_user_id() — never
-- from a parameter, which is finding C1's shape (database.md).
--
-- CONVENTIONS, because each one prevents a specific failure:
--   * Functions RETURN an outcome string instead of RAISING. A RAISE surfaces as
--     500 INTERNAL_ERROR (core/errors.py:138-167); an outcome lets the service
--     answer with a catalogued code (tdd.md §7.3).
--   * PL/pgSQL bodies start with `#variable_conflict use_column` and use
--     distinct OUT-parameter names: RETURNS TABLE columns become variables, and
--     an unqualified reference to a same-named column fails as "ambiguous".
--   * Capacity limits (300 active members, 50 active classrooms per teacher)
--     are checked AFTER a row lock, so two concurrent requests cannot both pass.
--     FOR NO KEY UPDATE serialises writers of the same space without blocking
--     the FOR KEY SHARE locks that foreign-key checks elsewhere take.
--   * Every function: SET search_path = public, pg_temp; REVOKE ALL FROM PUBLIC;
--     GRANT EXECUTE TO app_backend; COMMENT naming the calling endpoint first.
--
-- Idempotent: CREATE OR REPLACE throughout (all signatures are new).
-- ============================================================================

-- POST /api/spaces
CREATE OR REPLACE FUNCTION app.create_space(p_title text, p_subject uuid)
RETURNS TABLE (outcome text, new_space_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_user  uuid := app.current_user_id();
  v_space uuid;
BEGIN
  IF v_user IS NULL OR NOT EXISTS (
       SELECT 1 FROM public.app_user u
        WHERE u.id = v_user AND u.role = 'teacher'
          AND u.status = 'active' AND u.deleted_at IS NULL) THEN
    RETURN QUERY SELECT 'not_teacher'::text, NULL::uuid;
    RETURN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.subject WHERE id = p_subject) THEN
    RETURN QUERY SELECT 'unknown_subject'::text, NULL::uuid;
    RETURN;
  END IF;

  -- Serialise this teacher's creates, then cap active classrooms.
  PERFORM 1 FROM public.teacher_profile WHERE user_id = v_user FOR UPDATE;
  IF (SELECT count(*) FROM public.classroom_space
       WHERE owner_id = v_user AND status = 'active') >= 50 THEN
    RETURN QUERY SELECT 'classroom_limit'::text, NULL::uuid;
    RETURN;
  END IF;

  -- Owner decision 2026-10-03: creating a classroom IS the scope declaration,
  -- in the same transaction. A row an administrator revoked is left as it is.
  INSERT INTO public.teacher_subject_scope (teacher_id, subject_id)
  VALUES (v_user, p_subject)
  ON CONFLICT ON CONSTRAINT teacher_subject_scope_pkey DO NOTHING;
  IF EXISTS (SELECT 1 FROM public.teacher_subject_scope
              WHERE teacher_id = v_user AND subject_id = p_subject
                AND revoked_at IS NOT NULL) THEN
    RETURN QUERY SELECT 'scope_revoked'::text, NULL::uuid;
    RETURN;
  END IF;

  INSERT INTO public.classroom_space (owner_id, owner_role, subject_id, title)
  VALUES (v_user, 'teacher', p_subject, btrim(p_title))
  RETURNING id INTO v_space;

  RETURN QUERY SELECT 'created'::text, v_space;
END;
$$;

-- POST /api/spaces (first code) and POST /api/spaces/{id}/join-code {rotate}.
-- The code is minted in Python with `secrets` (codes.py); ck_join_code_format
-- enforces its shape here.
CREATE OR REPLACE FUNCTION app.rotate_join_code(p_space uuid, p_code text)
RETURNS TABLE (outcome text, new_code text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
BEGIN
  IF NOT app.owns_active_space(p_space) THEN
    RETURN QUERY SELECT 'forbidden'::text, NULL::text;
    RETURN;
  END IF;
  -- Without the lock, two concurrent rotations both pass the revoke and race
  -- the partial unique index — one of them as a 500.
  PERFORM 1 FROM public.classroom_space WHERE id = p_space FOR NO KEY UPDATE;
  UPDATE public.join_code SET revoked = true WHERE space_id = p_space AND revoked = false;
  INSERT INTO public.join_code (space_id, code) VALUES (p_space, p_code)
  ON CONFLICT (code) DO NOTHING;
  IF NOT FOUND THEN
    -- A collision with ANY code ever issued, revoked ones included (`code` is
    -- UNIQUE table-wide). The caller retries with a fresh code.
    RETURN QUERY SELECT 'collision'::text, NULL::text;
    RETURN;
  END IF;
  RETURN QUERY SELECT 'rotated'::text, p_code;
END;
$$;

-- POST /api/spaces/{id}/join-code {disable}. Works on an archived space too:
-- shutting a door must never be refused.
CREATE OR REPLACE FUNCTION app.disable_join_code(p_space uuid)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT app.owns_space(p_space) THEN
    RETURN false;
  END IF;
  UPDATE public.join_code SET revoked = true WHERE space_id = p_space AND revoked = false;
  RETURN true;
END;
$$;

-- POST /api/spaces/join — the ONLY enrolment writer (B9).
CREATE OR REPLACE FUNCTION app.join_space_by_code(p_code text)
RETURNS TABLE (outcome text, joined_space_id uuid, space_title text,
               space_subject text, space_board board_code, space_class_level smallint)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_user      uuid := app.current_user_id();
  -- Students copy codes off a board: tolerate case, spaces and dashes.
  v_code      text := upper(regexp_replace(coalesce(left(p_code, 64), ''), '[^A-Za-z0-9]', '', 'g'));
  v_profile   record;
  v_target    record;
  v_enrol     record;
  v_has_enrol boolean;
BEGIN
  SELECT sp.board, sp.class_level, sp.student_group INTO v_profile
    FROM public.app_user u
    JOIN public.student_profile sp ON sp.user_id = u.id
   WHERE u.id = v_user AND u.role = 'student'
     AND u.status = 'active' AND u.deleted_at IS NULL;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'not_student'::text, NULL::uuid, NULL::text, NULL::text,
                        NULL::board_code, NULL::smallint;
    RETURN;
  END IF;

  -- Defence in depth: the route already depends on require_guardian_verified.
  IF NOT app.caller_passes_guardian_gate() THEN
    RETURN QUERY SELECT 'gate_pending'::text, NULL::uuid, NULL::text, NULL::text,
                        NULL::board_code, NULL::smallint;
    RETURN;
  END IF;

  SELECT s.id, s.title, sub.id AS subject_id, sub.name AS subject_name,
         b.code AS board, cl.level AS lvl
    INTO v_target
    FROM public.join_code j
    JOIN public.classroom_space s ON s.id   = j.space_id
    JOIN public.subject sub       ON sub.id = s.subject_id
    JOIN public.class_level cl    ON cl.id  = sub.class_level_id
    JOIN public.board b           ON b.id   = cl.board_id
   WHERE j.code = v_code
     AND j.revoked = false
     AND (j.expires_at IS NULL OR j.expires_at > now())
     AND s.status = 'active';
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'invalid_code'::text, NULL::uuid, NULL::text, NULL::text,
                        NULL::board_code, NULL::smallint;
    RETURN;
  END IF;

  -- Serialise joins to this space, so the member cap cannot be raced.
  PERFORM 1 FROM public.classroom_space WHERE id = v_target.id FOR NO KEY UPDATE;

  SELECT e.id, e.left_at, e.removed_at INTO v_enrol
    FROM public.enrollment e
   WHERE e.space_id = v_target.id AND e.student_id = v_user;
  v_has_enrol := FOUND;

  -- A removed student learns NOTHING beyond "invalid code" — not that the class
  -- exists, and not that they were removed from it.
  IF v_has_enrol AND v_enrol.removed_at IS NOT NULL THEN
    RETURN QUERY SELECT 'invalid_code'::text, NULL::uuid, NULL::text, NULL::text,
                        NULL::board_code, NULL::smallint;
    RETURN;
  END IF;
  IF v_has_enrol AND v_enrol.left_at IS NULL THEN
    RETURN QUERY SELECT 'already_member'::text, v_target.id, v_target.title,
                        v_target.subject_name, v_target.board, v_target.lvl;
    RETURN;
  END IF;

  -- Owner decision 2026-10-03: board AND class AND the subject in the
  -- student's group, so a future per-subject report describes this student's
  -- own curriculum.
  IF v_target.board <> v_profile.board
     OR v_target.lvl <> v_profile.class_level
     OR NOT EXISTS (SELECT 1 FROM public.subject_group sg
                     WHERE sg.subject_id = v_target.subject_id
                       AND sg.student_group = v_profile.student_group) THEN
    RETURN QUERY SELECT 'class_mismatch'::text, NULL::uuid, v_target.title,
                        v_target.subject_name, v_target.board, v_target.lvl;
    RETURN;
  END IF;

  IF (SELECT count(*) FROM public.enrollment
       WHERE space_id = v_target.id AND left_at IS NULL) >= 300 THEN
    RETURN QUERY SELECT 'classroom_full'::text, NULL::uuid, NULL::text, NULL::text,
                        NULL::board_code, NULL::smallint;
    RETURN;
  END IF;

  IF v_has_enrol THEN
    -- A student who LEFT may rejoin. muted_at is deliberately preserved, or
    -- leaving and rejoining would clear a teacher's mute.
    UPDATE public.enrollment SET left_at = NULL, joined_at = now() WHERE id = v_enrol.id;
  ELSE
    INSERT INTO public.enrollment (space_id, student_id) VALUES (v_target.id, v_user);
  END IF;

  RETURN QUERY SELECT 'joined'::text, v_target.id, v_target.title,
                      v_target.subject_name, v_target.board, v_target.lvl;
END;
$$;

-- DELETE /api/spaces/{id}/membership. Leaving is a consent right
-- (prd.md:258): it works on an archived space and answers the same whether or
-- not the caller was a member.
CREATE OR REPLACE FUNCTION app.leave_space(p_space uuid)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  UPDATE public.enrollment SET left_at = now()
   WHERE space_id = p_space
     AND student_id = app.current_user_id()
     AND left_at IS NULL;
  RETURN FOUND;
END;
$$;

-- DELETE /api/spaces/{id}/members/{student_id}
CREATE OR REPLACE FUNCTION app.remove_student(p_space uuid, p_student uuid)
RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT app.owns_space(p_space) THEN
    RETURN false;
  END IF;
  UPDATE public.enrollment SET left_at = now(), removed_at = now()
   WHERE space_id = p_space AND student_id = p_student AND left_at IS NULL;
  RETURN FOUND;
END;
$$;

-- GET /api/spaces/{id}/people, and chat author names. `app_user_self_read`
-- (20260801120100:143-145) stops a plain join reading anyone else's name, so
-- this is the narrow door: the owner and ACTIVE members only, full_name only,
-- and mute flags to the owner only.
CREATE OR REPLACE FUNCTION app.space_people(p_space uuid)
RETURNS TABLE (user_id uuid, full_name text, is_owner boolean,
               joined_at timestamptz, muted boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  WITH me AS (SELECT app.owns_space(p_space) AS o, app.is_enrolled_in(p_space) AS m)
  SELECT s.owner_id, u.full_name, true, s.created_at, NULL::boolean
    FROM public.classroom_space s
    JOIN public.app_user u ON u.id = s.owner_id
   CROSS JOIN me
   WHERE s.id = p_space AND (me.o OR me.m)
  UNION ALL
  SELECT e.student_id, u.full_name, false, e.joined_at,
         CASE WHEN me.o THEN e.muted_at IS NOT NULL END
    FROM public.enrollment e
    JOIN public.app_user u ON u.id = e.student_id
   CROSS JOIN me
   WHERE e.space_id = p_space AND e.left_at IS NULL AND (me.o OR me.m);
$$;

-- GET /api/spaces and GET /api/spaces/{id}. One round trip; the teacher's name
-- is the hidden read a plain query could not make.
CREATE OR REPLACE FUNCTION app.my_spaces()
RETURNS TABLE (space_id uuid, title text, status space_status, subject_id uuid,
               subject_name text, board board_code, class_level smallint,
               owner_name text, viewer_role text, can_manage boolean,
               member_count integer, joined_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT s.id, s.title, s.status, sub.id, sub.name, b.code, cl.level, u.full_name,
         'owner'::text, app.owns_space(s.id),
         (SELECT count(*)::int FROM public.enrollment e
           WHERE e.space_id = s.id AND e.left_at IS NULL),
         NULL::timestamptz
    FROM public.classroom_space s
    JOIN public.subject sub    ON sub.id = s.subject_id
    JOIN public.class_level cl ON cl.id  = sub.class_level_id
    JOIN public.board b        ON b.id   = cl.board_id
    JOIN public.app_user u     ON u.id   = s.owner_id
   WHERE s.owner_id = app.current_user_id()
  UNION ALL
  SELECT s.id, s.title, s.status, sub.id, sub.name, b.code, cl.level, u.full_name,
         'member'::text, false, NULL::int, e.joined_at
    FROM public.enrollment e
    JOIN public.classroom_space s ON s.id   = e.space_id
    JOIN public.subject sub       ON sub.id = s.subject_id
    JOIN public.class_level cl    ON cl.id  = sub.class_level_id
    JOIN public.board b           ON b.id   = cl.board_id
    JOIN public.app_user u        ON u.id   = s.owner_id
   WHERE e.student_id = app.current_user_id()
     AND e.left_at IS NULL;
$$;

-- ── Grants (C5) ────────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION app.create_space(text, uuid)        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.rotate_join_code(uuid, text)    FROM PUBLIC;
REVOKE ALL ON FUNCTION app.disable_join_code(uuid)         FROM PUBLIC;
REVOKE ALL ON FUNCTION app.join_space_by_code(text)        FROM PUBLIC;
REVOKE ALL ON FUNCTION app.leave_space(uuid)               FROM PUBLIC;
REVOKE ALL ON FUNCTION app.remove_student(uuid, uuid)      FROM PUBLIC;
REVOKE ALL ON FUNCTION app.space_people(uuid)              FROM PUBLIC;
REVOKE ALL ON FUNCTION app.my_spaces()                     FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.create_space(text, uuid)     TO app_backend;
GRANT EXECUTE ON FUNCTION app.rotate_join_code(uuid, text) TO app_backend;
GRANT EXECUTE ON FUNCTION app.disable_join_code(uuid)      TO app_backend;
GRANT EXECUTE ON FUNCTION app.join_space_by_code(text)     TO app_backend;
GRANT EXECUTE ON FUNCTION app.leave_space(uuid)            TO app_backend;
GRANT EXECUTE ON FUNCTION app.remove_student(uuid, uuid)   TO app_backend;
GRANT EXECUTE ON FUNCTION app.space_people(uuid)           TO app_backend;
GRANT EXECUTE ON FUNCTION app.my_spaces()                  TO app_backend;

COMMENT ON FUNCTION app.create_space(text, uuid) IS
  'POST /api/spaces. Teacher-only, with the role read from the bound session (B10). '
  'Self-declares teacher_subject_scope in the same transaction; refuses a revoked scope; '
  'caps 50 active classrooms per teacher.';
COMMENT ON FUNCTION app.rotate_join_code(uuid, text) IS
  'POST /api/spaces, POST /api/spaces/{id}/join-code {rotate}. The only join_code writer '
  '(reverses database.md:864-868). Returns collision for a retry with a fresh code.';
COMMENT ON FUNCTION app.disable_join_code(uuid) IS
  'POST /api/spaces/{id}/join-code {disable}. Owner-only; allowed on an archived space.';
COMMENT ON FUNCTION app.join_space_by_code(text) IS
  'POST /api/spaces/join. The only enrolment writer (B9). A removed student gets the same '
  'outcome as an unknown code. Board, class and group must match; the guardian gate is '
  're-checked; 300 active members per classroom.';
COMMENT ON FUNCTION app.leave_space(uuid) IS
  'DELETE /api/spaces/{id}/membership. Idempotent; allowed on an archived space.';
COMMENT ON FUNCTION app.remove_student(uuid, uuid) IS
  'DELETE /api/spaces/{id}/members/{student_id}. Sets removed_at, which blocks rejoining.';
COMMENT ON FUNCTION app.space_people(uuid) IS
  'GET /api/spaces/{id}/people. Owner and active members only; full_name only; mute flags '
  'to the owner only.';
COMMENT ON FUNCTION app.my_spaces() IS
  'GET /api/spaces, GET /api/spaces/{id}. Spaces the caller owns or is actively enrolled in.';
