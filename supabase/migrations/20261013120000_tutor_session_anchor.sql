-- ============================================================================
-- EduBridge AI — the tutor session's anchor (tdd.md §3.2a, §5.3f)
--
-- `chat_session` is (id, student_id, started_at, ended_at) and nothing more, so
-- a session cannot say what it is ABOUT. The Class 9 Physics tutor needs that:
-- a session opened from a chapter should rank that chapter's pages ahead of the
-- rest, and a resumed session should still know which chapter it was opened
-- from. Three nullable columns.
--
-- ⚠️ THE ANCHOR IS A RANKING PRIOR, NOT A FILTER, AND THAT IS WHY THESE ARE
--    NULLABLE AND WHY THERE IS NO FOREIGN KEY TO A CHAPTER TABLE.
--
--    Hard-scoping retrieval to the anchored chapter breaks the most ordinary
--    thing a student does — asking a prerequisite question. "What is a mole
--    again?" asked inside Thermal Properties would return nothing useful and
--    give no indication why, because the pages that answer it were excluded
--    before scoring. So the application adds a score bonus to in-chapter pages
--    and lets an out-of-chapter page win when it scores better. A NOT NULL
--    column, or a FK that made the anchor authoritative, would both invite the
--    filter reading. The column is a hint; the retriever decides.
--
-- ⚠️ `chapter` IS DELIBERATELY NOT A FOREIGN KEY.
--    The curriculum taxonomy exists (`chapter`, keyed to `subject`), but the
--    pilot's unit is a PAGE SCAN of one specific book, not a taxonomy row — the
--    knowledge-base tables are explicitly deferred in `initial_schema.sql`'s
--    SCOPE block. A FK here would assert a join the pilot cannot honour and
--    would have to be dropped when the real KB lands. A smallint that means
--    "chapter 7 of the book this session is about" is the honest shape for now.
--
-- WHY THERE IS NO MIGRATION FOR CITATIONS.
--    An answer cites textbook pages, and `message.slo_refs uuid[]` is the
--    column designed for citations — but it references `slo` rows, and there
--    are none, for the same deferred-KB reason. Rather than widen `message` or
--    add a table, a cited page set goes in `visual_aid.payload` (jsonb) with
--    `kind = 'figure'`, a label `visual_kind` ALREADY carries. So the pilot
--    cites pages with no schema change at all, and `slo_refs` stays NULL and
--    unmisused, ready for its real purpose.
--
-- RLS: unchanged and already correct. `chat_session_owner` is a single
--    `FOR ALL` policy keyed on `student_id = app.current_user_id()`, so these
--    columns inherit owner-only access. Chat content has NO teacher, parent or
--    admin read path (prd.md §4.2, TEL-3) and this migration does not open one.
--
-- GRANTS: not needed. `chat_session` still carries the table-wide grant from
--    `20260801120100`; no later migration narrowed it to a column list, so a
--    new column is covered. (`auth_token` and the owner-scoped analytics tables
--    WERE narrowed — had this been one of those, each new column would need an
--    explicit GRANT, which is the trap `20260816170000` documents.)
--
-- Metadata-only: `chat_session` is not partitioned and all three columns are
-- nullable with no default, so no table rewrite and no backfill.
--
-- Idempotent: `ADD COLUMN IF NOT EXISTS` is a no-op on re-run, and each CHECK
-- is created only when absent. ⚠️ Postgres has no `ADD CONSTRAINT IF NOT
-- EXISTS`, so the catalogue guard below is the only re-runnable form — and
-- every file here must be re-runnable because the Supabase CLI does not wrap a
-- file in a transaction, so a half-applied file has to be safe to apply again.
-- ============================================================================

-- ── 1. The columns ──────────────────────────────────────────────────────────

ALTER TABLE public.chat_session
  ADD COLUMN IF NOT EXISTS subject text;

ALTER TABLE public.chat_session
  ADD COLUMN IF NOT EXISTS class_level smallint;

ALTER TABLE public.chat_session
  ADD COLUMN IF NOT EXISTS chapter smallint;

COMMENT ON COLUMN public.chat_session.subject IS
  'What this session is about, as a plain label (the pilot writes ''physics''). '
  'NOT a foreign key to the subject taxonomy: the pilot''s unit is one book''s '
  'page scans, not a taxonomy row, and the knowledge-base tables are deferred. '
  'Nullable — a session with no anchor is valid and ranks nothing specially.';

COMMENT ON COLUMN public.chat_session.class_level IS
  'The class this session was opened for, 9-12. Recorded on the session rather '
  'than read from student_profile at query time so a session stays '
  'interpretable after the student moves up a class.';

COMMENT ON COLUMN public.chat_session.chapter IS
  'The anchored chapter. A RANKING PRIOR, never a filter: in-chapter pages get '
  'a score bonus and an out-of-chapter page still wins when it scores better, '
  'so a prerequisite question asked inside a chapter does not fail silently. '
  'Nullable, and no FK — see this migration''s header.';

-- ── 2. Bounds the application also enforces, enforced again here ────────────
--
-- `user-stories.md` card 1.5 promises every request is checked by the
-- application AND again by the database, and the August 2026 audit found the
-- database would not catch a missed check on most tables (CLAUDE.md §6). These
-- two CHECKs are cheap, and are the layer that holds if a future caller writes
-- the anchor without going through the tutor route.
--
-- `class_level` is bounded to the four classes the product serves. `chapter` is
-- bounded only to "positive", NOT to 1-9: nine is the Physics 9 chapter count,
-- and hardcoding one book's structure into a shared table would have to be
-- dropped the moment a second book arrives.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.chat_session'::regclass
      AND conname = 'ck_chat_session_class_level'
  ) THEN
    ALTER TABLE public.chat_session
      ADD CONSTRAINT ck_chat_session_class_level
      CHECK (class_level IS NULL OR class_level BETWEEN 9 AND 12);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.chat_session'::regclass
      AND conname = 'ck_chat_session_chapter'
  ) THEN
    ALTER TABLE public.chat_session
      ADD CONSTRAINT ck_chat_session_chapter
      CHECK (chapter IS NULL OR chapter > 0);
  END IF;
END
$$;

-- ── 3. Resuming a session reads it by owner, newest first ───────────────────
--
-- `ix_chat_session_student (student_id, started_at DESC)` already serves the
-- session list, so no index is added. Stated explicitly because the obvious
-- instinct is to index the anchor: nothing queries BY chapter — the anchor is
-- read off a session the student already chose, never used to find sessions.
