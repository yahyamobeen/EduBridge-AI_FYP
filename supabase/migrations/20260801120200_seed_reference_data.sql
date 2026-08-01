-- ============================================================================
-- EduBridge AI — Reference seed data
--
-- Boards, class levels, subjects and elective-group mappings.
--
-- SUBJECT MATRIX (as specified by the team)
--   Class  9 (science) : English, Urdu, Maths, Physics, Chemistry, Biology,          Islamiat, Pak Studies, Quran
--   Class  9 (computer): English, Urdu, Maths, Physics, Chemistry, Computer Science, Islamiat, Pak Studies, Quran
--   Class 10 (science) : English, Urdu, Maths, Physics, Chemistry, Biology,          Islamiat, Pak Studies, Quran
--   Class 10 (computer): English, Urdu, Maths, Physics, Chemistry, Computer Science, Islamiat, Pak Studies, Quran
--   Class 11 (pre-med) : English, Urdu, Physics, Chemistry, Biology,                 Islamiat, Quran
--   Class 11 (pre-eng) : English, Urdu, Physics, Chemistry, Mathematics,             Islamiat, Quran
--   Class 11 (ics)     : English, Urdu, Physics, Chemistry, Mathematics, Comp Sci,   Islamiat, Quran
--   Class 12 (pre-med) : English, Urdu, Physics, Chemistry, Biology,                 Pak Studies, Quran
--   Class 12 (pre-eng) : English, Urdu, Physics, Chemistry, Mathematics,             Pak Studies, Quran
--   Class 12 (ics)     : English, Urdu, Physics, Chemistry, Mathematics, Comp Sci,   Pak Studies, Quran
--
--   Islamiat runs in 9, 10, 11.   Pakistan Studies runs in 9, 10, 12.
--   Quran Translation runs in all four years.
--
-- A subject exists ONCE per (board, class); subject_group records which
-- elective groups take it, so shared subjects are never duplicated.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- Boards ---------------------------------------------------------------------
INSERT INTO public.board (code, name) VALUES
  ('PCTB', 'Punjab Curriculum and Textbook Board'),
  ('STBB', 'Sindh Textbook Board')
ON CONFLICT (code) DO NOTHING;

-- Class levels 9-12 for every board ------------------------------------------
INSERT INTO public.class_level (board_id, level)
SELECT b.id, l.level
FROM public.board b
CROSS JOIN (VALUES (9::smallint), (10), (11), (12)) AS l(level)
ON CONFLICT (board_id, level) DO NOTHING;

-- Subjects per class ---------------------------------------------------------
-- content_strategy drives how the agent is permitted to answer (tdd §4.6).
INSERT INTO public.subject (class_level_id, name, content_strategy)
SELECT cl.id, s.name, s.strategy::content_strategy
FROM public.class_level cl
JOIN (VALUES
  -- ---- Class 9 -------------------------------------------------------------
  (9::smallint,  'English',           'english_language'),
  (9,            'Urdu',              'branch_b_urdu_native'),
  (9,            'Mathematics',       'branch_a_english_source'),
  (9,            'Physics',           'branch_a_english_source'),
  (9,            'Chemistry',         'branch_a_english_source'),
  (9,            'Biology',           'branch_a_english_source'),
  (9,            'Computer Science',  'branch_a_english_source'),
  (9,            'Islamiat',          'branch_a_english_source'),
  (9,            'Pakistan Studies',  'branch_a_english_source'),
  (9,            'Quran Translation', 'religious_verbatim'),
  -- ---- Class 10 ------------------------------------------------------------
  (10,           'English',           'english_language'),
  (10,           'Urdu',              'branch_b_urdu_native'),
  (10,           'Mathematics',       'branch_a_english_source'),
  (10,           'Physics',           'branch_a_english_source'),
  (10,           'Chemistry',         'branch_a_english_source'),
  (10,           'Biology',           'branch_a_english_source'),
  (10,           'Computer Science',  'branch_a_english_source'),
  (10,           'Islamiat',          'branch_a_english_source'),
  (10,           'Pakistan Studies',  'branch_a_english_source'),
  (10,           'Quran Translation', 'religious_verbatim'),
  -- ---- Class 11 (no Pakistan Studies) --------------------------------------
  (11,           'English',           'english_language'),
  (11,           'Urdu',              'branch_b_urdu_native'),
  (11,           'Mathematics',       'branch_a_english_source'),
  (11,           'Physics',           'branch_a_english_source'),
  (11,           'Chemistry',         'branch_a_english_source'),
  (11,           'Biology',           'branch_a_english_source'),
  (11,           'Computer Science',  'branch_a_english_source'),
  (11,           'Islamiat',          'branch_a_english_source'),
  (11,           'Quran Translation', 'religious_verbatim'),
  -- ---- Class 12 (no Islamiat) ----------------------------------------------
  (12,           'English',           'english_language'),
  (12,           'Urdu',              'branch_b_urdu_native'),
  (12,           'Mathematics',       'branch_a_english_source'),
  (12,           'Physics',           'branch_a_english_source'),
  (12,           'Chemistry',         'branch_a_english_source'),
  (12,           'Biology',           'branch_a_english_source'),
  (12,           'Computer Science',  'branch_a_english_source'),
  (12,           'Pakistan Studies',  'branch_a_english_source'),
  (12,           'Quran Translation', 'religious_verbatim')
) AS s(level, name, strategy) ON s.level = cl.level
ON CONFLICT (class_level_id, name) DO NOTHING;

-- Group mappings -------------------------------------------------------------
-- Rule: every subject applies to every group valid for its class, EXCEPT
--   Biology          -> science (Matric) and pre_medical (FSc) only
--   Computer Science -> computer (Matric) and ics (FSc) only
--   Mathematics      -> not taken by pre_medical at FSc level
INSERT INTO public.subject_group (subject_id, student_group)
SELECT sub.id, g.grp
FROM public.subject sub
JOIN public.class_level cl ON cl.id = sub.class_level_id
CROSS JOIN LATERAL (
  SELECT unnest(
    CASE WHEN cl.level IN (9,10)
         THEN ARRAY['science','computer']::student_group[]
         ELSE ARRAY['pre_medical','pre_engineering','ics']::student_group[]
    END
  ) AS grp
) g
WHERE NOT (
     (sub.name = 'Biology'          AND g.grp NOT IN ('science','pre_medical'))
  OR (sub.name = 'Computer Science' AND g.grp NOT IN ('computer','ics'))
  OR (sub.name = 'Mathematics'      AND cl.level IN (11,12) AND g.grp = 'pre_medical')
)
ON CONFLICT (subject_id, student_group) DO NOTHING;

-- Sanity check ---------------------------------------------------------------
DO $$
DECLARE
  n_boards int; n_classes int; n_subjects int; n_map int;
  c9_sci int; c11_med int; c11_ics int; c12_eng int;
BEGIN
  SELECT count(*) INTO n_boards   FROM public.board;
  SELECT count(*) INTO n_classes  FROM public.class_level;
  SELECT count(*) INTO n_subjects FROM public.subject;
  SELECT count(*) INTO n_map      FROM public.subject_group;

  -- Per-group subject counts for one board, to verify the exclusion rule
  SELECT count(*) INTO c9_sci FROM public.subject s
    JOIN public.class_level cl ON cl.id = s.class_level_id
    JOIN public.board b ON b.id = cl.board_id
    JOIN public.subject_group sg ON sg.subject_id = s.id
    WHERE b.code = 'PCTB' AND cl.level = 9  AND sg.student_group = 'science';
  SELECT count(*) INTO c11_med FROM public.subject s
    JOIN public.class_level cl ON cl.id = s.class_level_id
    JOIN public.board b ON b.id = cl.board_id
    JOIN public.subject_group sg ON sg.subject_id = s.id
    WHERE b.code = 'PCTB' AND cl.level = 11 AND sg.student_group = 'pre_medical';
  SELECT count(*) INTO c11_ics FROM public.subject s
    JOIN public.class_level cl ON cl.id = s.class_level_id
    JOIN public.board b ON b.id = cl.board_id
    JOIN public.subject_group sg ON sg.subject_id = s.id
    WHERE b.code = 'PCTB' AND cl.level = 11 AND sg.student_group = 'ics';
  SELECT count(*) INTO c12_eng FROM public.subject s
    JOIN public.class_level cl ON cl.id = s.class_level_id
    JOIN public.board b ON b.id = cl.board_id
    JOIN public.subject_group sg ON sg.subject_id = s.id
    WHERE b.code = 'PCTB' AND cl.level = 12 AND sg.student_group = 'pre_engineering';

  RAISE NOTICE 'Seeded % boards, % class levels, % subjects, % group mappings',
    n_boards, n_classes, n_subjects, n_map;
  RAISE NOTICE 'PCTB subject counts -> C9 science: % (expect 9), C11 pre-med: % (expect 7), C11 ICS: % (expect 8), C12 pre-eng: % (expect 7)',
    c9_sci, c11_med, c11_ics, c12_eng;

  IF n_subjects <> 76 THEN
    RAISE WARNING 'Expected 76 subject rows (2 boards x [10+10+9+9]), found %', n_subjects;
  END IF;
  IF c9_sci <> 9 OR c11_med <> 7 OR c11_ics <> 8 OR c12_eng <> 7 THEN
    RAISE WARNING 'Group mapping counts do not match the specified matrix';
  END IF;
END
$$;
