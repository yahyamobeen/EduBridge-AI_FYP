-- ============================================================================
-- EduBridge AI — Initial schema (OLTP)
-- Target      : Supabase (PostgreSQL 15+)
-- Implements  : tdd.md §5.3–5.4, prd.md §9
--
-- SCOPE
--   Included : identity/RBAC, curriculum taxonomy, classroom, assessment,
--              learner analytics, tutor sessions, security & platform logs
--   Deferred : knowledge-base content (kb_document, curriculum_item,
--              textbook_figure, urdu_note_item, glossary_term) + vector store
--              -> to be designed with the chatbot layer
--
-- AUTH MODEL
--   Application-managed: FastAPI + argon2 password hashing + own JWTs.
--   Supabase Auth (auth.users) is intentionally NOT used.
--
-- NOTE ON UUIDs
--   gen_random_uuid() is built into PostgreSQL 13+ (UUIDv4).
--   On PostgreSQL 18+ you may switch these DEFAULTs to uuidv7() for
--   time-ordered keys and better index locality.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS citext;   -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fuzzy text search

-- ----------------------------------------------------------------------------
-- Helper schema (RLS helpers live here; see the RLS migration)
-- ----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS app;

-- ----------------------------------------------------------------------------
-- Enumerated types  (status/category columns are never free text)
-- ----------------------------------------------------------------------------
CREATE TYPE user_role          AS ENUM ('student','teacher','parent','admin');
CREATE TYPE user_status        AS ENUM ('active','suspended','deleted');
CREATE TYPE board_code         AS ENUM ('PCTB','STBB');
CREATE TYPE medium_code        AS ENUM ('en','ur');
CREATE TYPE language_code      AS ENUM ('en','ur','roman_ur');

-- Elective group. Matric (9-10): science | computer.
-- FSc (11-12): pre_medical | pre_engineering | ics.
CREATE TYPE student_group      AS ENUM ('science','computer','pre_medical','pre_engineering','ics');

-- How the agent is allowed to answer for a subject (tdd §4.6 routing).
--   branch_a_english_source : English KB + cross-lingual retrieval, generate in student's language.
--                             Covers every dual-medium subject: the sciences, Maths, Computer
--                             Science, Islamiat and Pakistan Studies (all published in both
--                             English and Urdu medium with the same syllabus).
--   branch_b_urdu_native    : Urdu notes corpus, retrieval-first + exam templates.
--                             Urdu Lazmi only - the one natively-Urdu subject.
--   religious_verbatim      : retrieval ONLY - text returned word for word, never composed
--   english_language        : English-language subject - grammar/essay/comprehension templates
CREATE TYPE content_strategy   AS ENUM (
  'branch_a_english_source',
  'branch_b_urdu_native',
  'religious_verbatim',
  'english_language'
);
CREATE TYPE guardian_status    AS ENUM ('pending','verified','revoked');
CREATE TYPE token_kind         AS ENUM ('refresh','guardian_invite','email_verify','password_reset');
CREATE TYPE space_owner_role   AS ENUM ('teacher','parent');
CREATE TYPE space_status       AS ENUM ('active','archived');
CREATE TYPE quiz_source        AS ENUM ('teacher','agent_draft');
CREATE TYPE quiz_attempt_state AS ENUM ('not_started','in_progress','submitted','auto_submitted','graded');
CREATE TYPE message_role       AS ENUM ('student','assistant','system');
CREATE TYPE visual_kind        AS ENUM ('figure','katex','mermaid','chart','functionplot','curated','text');
CREATE TYPE component_kind     AS ENUM ('skill','mcp_server');
CREATE TYPE component_status   AS ENUM ('submitted','admitted','blocked','suspended');
CREATE TYPE vetting_verdict    AS ENUM ('pending','admitted','blocked');

-- ----------------------------------------------------------------------------
-- Shared trigger: maintain updated_at
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ============================================================================
-- 1. IDENTITY & RBAC                                            (tdd §5.3a)
-- ============================================================================

CREATE TABLE public.app_user (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  email         citext      NOT NULL UNIQUE,
  password_hash text        NOT NULL,              -- argon2id, never plaintext
  role          user_role   NOT NULL,
  status        user_status NOT NULL DEFAULT 'active',
  full_name     text,
  email_verified_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz
);
CREATE TRIGGER trg_app_user_updated BEFORE UPDATE ON public.app_user
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX ix_app_user_role ON public.app_user(role) WHERE deleted_at IS NULL;

-- Student profile ------------------------------------------------------------
CREATE TABLE public.student_profile (
  user_id       uuid          PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
  board         board_code    NOT NULL,
  class_level   smallint      NOT NULL CHECK (class_level BETWEEN 9 AND 12),
  student_group student_group NOT NULL,
  medium        medium_code   NOT NULL,
  language_pref language_code NOT NULL DEFAULT 'en',
  created_at    timestamptz   NOT NULL DEFAULT now(),
  updated_at    timestamptz   NOT NULL DEFAULT now(),
  -- Matric groups and FSc groups are not interchangeable
  CONSTRAINT ck_group_matches_class CHECK (
       (class_level IN (9,10)  AND student_group IN ('science','computer'))
    OR (class_level IN (11,12) AND student_group IN ('pre_medical','pre_engineering','ics'))
  )
);
CREATE TRIGGER trg_student_profile_updated BEFORE UPDATE ON public.student_profile
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX ix_student_board_class ON public.student_profile(board, class_level, student_group);

CREATE TABLE public.teacher_profile (
  user_id    uuid        PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
  institution text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.parent_profile (
  user_id    uuid        PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.admin_profile (
  user_id    uuid        PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
  scope      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Parental-consent gate ------------------------------------------------------
-- Classes 9-10 require a VERIFIED guardian link before full access (prd §4.3).
-- CHECK prevents a student self-registering as their own parent (tdd §14 fix 3).
CREATE TABLE public.guardian_link (
  id                  uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id           uuid            NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  student_id          uuid            NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  status              guardian_status NOT NULL DEFAULT 'pending',
  verification_method text,           -- 'oob_email' | 'manual_review' | 'phone'
  verified_at         timestamptz,
  created_at          timestamptz     NOT NULL DEFAULT now(),
  updated_at          timestamptz     NOT NULL DEFAULT now(),
  CONSTRAINT ck_guardian_not_self CHECK (parent_id <> student_id),
  CONSTRAINT ck_guardian_verified_has_ts
    CHECK (status <> 'verified' OR verified_at IS NOT NULL),
  CONSTRAINT uq_guardian_pair UNIQUE (parent_id, student_id)
);
CREATE TRIGGER trg_guardian_link_updated BEFORE UPDATE ON public.guardian_link
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX ix_guardian_student_verified
  ON public.guardian_link(student_id) WHERE status = 'verified';
CREATE INDEX ix_guardian_parent ON public.guardian_link(parent_id);

-- Tokens (refresh, guardian invite, email verify) -----------------------------
CREATE TABLE public.auth_token (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  kind       token_kind  NOT NULL,
  token_hash text        NOT NULL UNIQUE,   -- store the hash, never the token
  revoked    boolean     NOT NULL DEFAULT false,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_auth_token_user_kind
  ON public.auth_token(user_id, kind) WHERE revoked = false;

-- ============================================================================
-- 2. CURRICULUM TAXONOMY                                        (tdd §5.3b)
--    Content/KB tables are deferred to the chatbot layer.
--    SLOs are soft-retired, never deleted, so historical mastery keeps meaning.
-- ============================================================================

CREATE TABLE public.board (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  code       board_code  NOT NULL UNIQUE,
  name       text        NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.class_level (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  board_id   uuid        NOT NULL REFERENCES public.board(id) ON DELETE RESTRICT,
  level      smallint    NOT NULL CHECK (level BETWEEN 9 AND 12),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_class_level UNIQUE (board_id, level)
);

-- A subject is defined once per (board, class) — NOT per group — so the
-- curriculum content for e.g. "English, Class 9" is never duplicated across
-- the science and computer groups. Group applicability lives in subject_group.
CREATE TABLE public.subject (
  id                uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
  class_level_id    uuid             NOT NULL REFERENCES public.class_level(id) ON DELETE RESTRICT,
  name              text             NOT NULL,
  content_strategy  content_strategy NOT NULL,   -- drives agent routing (tdd §4.6)
  created_at        timestamptz      NOT NULL DEFAULT now(),
  CONSTRAINT uq_subject UNIQUE (class_level_id, name)
);
CREATE INDEX ix_subject_class    ON public.subject(class_level_id);
CREATE INDEX ix_subject_strategy ON public.subject(content_strategy);

-- Which elective groups actually take each subject.
-- e.g. Class 11 Biology -> pre_medical only; Class 11 Mathematics -> pre_engineering, ics.
CREATE TABLE public.subject_group (
  subject_id    uuid          NOT NULL REFERENCES public.subject(id) ON DELETE CASCADE,
  student_group student_group NOT NULL,
  PRIMARY KEY (subject_id, student_group)
);
CREATE INDEX ix_subject_group_grp ON public.subject_group(student_group);

CREATE TABLE public.chapter (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid        NOT NULL REFERENCES public.subject(id) ON DELETE RESTRICT,
  number     smallint    NOT NULL,
  title      text        NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_chapter UNIQUE (subject_id, number)
);
CREATE INDEX ix_chapter_subject ON public.chapter(subject_id);

CREATE TABLE public.slo (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  chapter_id          uuid        NOT NULL REFERENCES public.chapter(id) ON DELETE RESTRICT,
  code                text        NOT NULL,
  description         text        NOT NULL,
  effective_from_year smallint,
  retired_at          timestamptz,          -- soft-retire on syllabus change
  created_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_slo UNIQUE (chapter_id, code)
);
CREATE INDEX ix_slo_chapter_active ON public.slo(chapter_id) WHERE retired_at IS NULL;

-- Teacher subject scope (M:N) — least privilege (tdd §14 fix 7) ---------------
CREATE TABLE public.teacher_subject_scope (
  teacher_id uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  subject_id uuid        NOT NULL REFERENCES public.subject(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (teacher_id, subject_id)
);
CREATE INDEX ix_tss_subject ON public.teacher_subject_scope(subject_id);

-- ============================================================================
-- 3. CLASSROOM & SPACES                                         (tdd §5.3e)
--    Joining a space IS the consent record (prd §15 CL-1).
-- ============================================================================

CREATE TABLE public.classroom_space (
  id         uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id   uuid             NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  owner_role space_owner_role NOT NULL,
  subject_id uuid             REFERENCES public.subject(id) ON DELETE RESTRICT, -- NULL for parent spaces
  title      text             NOT NULL,
  status     space_status     NOT NULL DEFAULT 'active',
  created_at timestamptz      NOT NULL DEFAULT now(),
  updated_at timestamptz      NOT NULL DEFAULT now(),
  -- a teacher space must declare its subject (subject-scoping depends on it)
  CONSTRAINT ck_teacher_space_has_subject
    CHECK (owner_role <> 'teacher' OR subject_id IS NOT NULL)
);
CREATE TRIGGER trg_space_updated BEFORE UPDATE ON public.classroom_space
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX ix_space_owner ON public.classroom_space(owner_id);

CREATE TABLE public.join_code (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id   uuid        NOT NULL REFERENCES public.classroom_space(id) ON DELETE CASCADE,
  code       text        NOT NULL UNIQUE,
  revoked    boolean     NOT NULL DEFAULT false,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_join_code_active ON public.join_code(space_id) WHERE revoked = false;

CREATE TABLE public.enrollment (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id   uuid        NOT NULL REFERENCES public.classroom_space(id) ON DELETE CASCADE,
  student_id uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  joined_at  timestamptz NOT NULL DEFAULT now(),
  left_at    timestamptz,
  CONSTRAINT uq_enrollment UNIQUE (space_id, student_id)
);
CREATE INDEX ix_enrollment_student_active
  ON public.enrollment(student_id) WHERE left_at IS NULL;
CREATE INDEX ix_enrollment_space_active
  ON public.enrollment(space_id) WHERE left_at IS NULL;

CREATE TABLE public.announcement (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id   uuid        NOT NULL REFERENCES public.classroom_space(id) ON DELETE CASCADE,
  author_id  uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  body       text        NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_announcement_space ON public.announcement(space_id, created_at DESC);

-- ============================================================================
-- 4. ASSESSMENT                                                 (tdd §5.3c)
--    Answer keys live in a SEPARATE table so no client-facing serialization
--    can ever leak them (NFR-8 / tdd §14 fix 5).
-- ============================================================================

CREATE TABLE public.past_paper (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  board_id       uuid        NOT NULL REFERENCES public.board(id) ON DELETE RESTRICT,
  class_level_id uuid        NOT NULL REFERENCES public.class_level(id) ON DELETE RESTRICT,
  subject_id     uuid        NOT NULL REFERENCES public.subject(id) ON DELETE RESTRICT,
  year           smallint    NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_past_paper UNIQUE (board_id, class_level_id, subject_id, year)
);

CREATE TABLE public.question (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  past_paper_id  uuid        REFERENCES public.past_paper(id) ON DELETE SET NULL,
  subject_id     uuid        NOT NULL REFERENCES public.subject(id) ON DELETE RESTRICT,
  primary_slo_id uuid        REFERENCES public.slo(id) ON DELETE RESTRICT,
  stem           text        NOT NULL,
  choices        jsonb,      -- MCQ options; NULL for free-response
  marks          smallint    NOT NULL DEFAULT 1 CHECK (marks > 0),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_question_subject     ON public.question(subject_id);
CREATE INDEX ix_question_primary_slo ON public.question(primary_slo_id);
CREATE INDEX ix_question_choices_gin ON public.question USING gin (choices);

-- SERVER-ONLY. Never expose in any client-facing schema, route or view.
CREATE TABLE public.question_key (
  question_id uuid        PRIMARY KEY REFERENCES public.question(id) ON DELETE CASCADE,
  answer_key  text        NOT NULL,
  rationale   text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Fractional SLO attribution so a wrong answer is never double-counted
-- or dropped across an M:N mapping (tdd §14 fix 9).
CREATE TABLE public.question_slo (
  question_id uuid    NOT NULL REFERENCES public.question(id) ON DELETE CASCADE,
  slo_id      uuid    NOT NULL REFERENCES public.slo(id)      ON DELETE RESTRICT,
  weight      numeric(4,3) NOT NULL DEFAULT 1.000 CHECK (weight > 0 AND weight <= 1),
  is_primary  boolean NOT NULL DEFAULT false,
  PRIMARY KEY (question_id, slo_id)
);
CREATE INDEX ix_question_slo_slo ON public.question_slo(slo_id);

CREATE TABLE public.item_difficulty (
  question_id   uuid        PRIMARY KEY REFERENCES public.question(id) ON DELETE CASCADE,
  irt_a         real,       -- discrimination
  irt_b         real,       -- difficulty
  irt_c         real,       -- guessing
  calibrated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.slo_frequency_cluster (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  slo_id        uuid        NOT NULL REFERENCES public.slo(id)   ON DELETE RESTRICT,
  board_id      uuid        NOT NULL REFERENCES public.board(id) ON DELETE RESTRICT,
  freq_score    real        NOT NULL CHECK (freq_score >= 0),
  years_covered smallint    NOT NULL DEFAULT 5,
  computed_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_slo_freq UNIQUE (slo_id, board_id)
);
CREATE INDEX ix_slo_freq_score ON public.slo_frequency_cluster(board_id, freq_score DESC);

CREATE TABLE public.quiz (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id    uuid        REFERENCES public.classroom_space(id) ON DELETE CASCADE,
  subject_id  uuid        NOT NULL REFERENCES public.subject(id) ON DELETE RESTRICT,
  created_by  uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE RESTRICT,
  source      quiz_source NOT NULL DEFAULT 'teacher',
  title       text        NOT NULL,
  topic_tags  text[],
  time_open   timestamptz NOT NULL,
  time_close  timestamptz NOT NULL,
  one_attempt boolean     NOT NULL DEFAULT true,
  shuffle     boolean     NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_quiz_window CHECK (time_close > time_open)
);
CREATE TRIGGER trg_quiz_updated BEFORE UPDATE ON public.quiz
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX ix_quiz_space ON public.quiz(space_id);
CREATE INDEX ix_quiz_open  ON public.quiz(time_close) WHERE one_attempt = true;

CREATE TABLE public.quiz_question (
  quiz_id     uuid     NOT NULL REFERENCES public.quiz(id)     ON DELETE CASCADE,
  question_id uuid     NOT NULL REFERENCES public.question(id) ON DELETE RESTRICT,
  position    smallint NOT NULL,
  PRIMARY KEY (quiz_id, question_id)
);

CREATE TABLE public.quiz_attempt (
  id           uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
  quiz_id      uuid               NOT NULL REFERENCES public.quiz(id)      ON DELETE CASCADE,
  student_id   uuid               NOT NULL REFERENCES public.app_user(id)  ON DELETE CASCADE,
  state        quiz_attempt_state NOT NULL DEFAULT 'not_started',
  started_at   timestamptz,
  submitted_at timestamptz,
  score        numeric(5,2)       CHECK (score >= 0),
  version      integer            NOT NULL DEFAULT 0,   -- optimistic lock
  created_at   timestamptz        NOT NULL DEFAULT now(),
  CONSTRAINT uq_attempt_one_per_student UNIQUE (quiz_id, student_id)
);
-- Sweeper job scans this partial index to auto-submit abandoned attempts
CREATE INDEX ix_attempt_in_progress
  ON public.quiz_attempt(quiz_id) WHERE state = 'in_progress';
CREATE INDEX ix_attempt_student ON public.quiz_attempt(student_id);

CREATE TABLE public.attempt_answer (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id  uuid        NOT NULL REFERENCES public.quiz_attempt(id) ON DELETE CASCADE,
  question_id uuid        NOT NULL REFERENCES public.question(id)     ON DELETE RESTRICT,
  response    text,
  correct     boolean,    -- graded server-side only
  answered_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_attempt_answer UNIQUE (attempt_id, question_id)
);

-- ============================================================================
-- 5. LEARNER ANALYTICS — current state                          (tdd §5.3d)
--    Historical snapshots live in the analytics star schema.
-- ============================================================================

CREATE TABLE public.mastery_estimate (
  student_id uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  slo_id     uuid        NOT NULL REFERENCES public.slo(id)      ON DELETE RESTRICT,
  p_mastery  real        NOT NULL DEFAULT 0.10 CHECK (p_mastery BETWEEN 0 AND 1),
  p_transit  real        NOT NULL DEFAULT 0.20 CHECK (p_transit BETWEEN 0 AND 1),
  p_guess    real        NOT NULL DEFAULT 0.25 CHECK (p_guess   BETWEEN 0 AND 1),
  p_slip     real        NOT NULL DEFAULT 0.10 CHECK (p_slip    BETWEEN 0 AND 1),
  observations integer   NOT NULL DEFAULT 0,
  version    integer     NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (student_id, slo_id)
);
CREATE INDEX ix_mastery_weak ON public.mastery_estimate(student_id, p_mastery);

CREATE TABLE public.coverage_record (
  id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id   uuid         NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  subject_id   uuid         NOT NULL REFERENCES public.subject(id)  ON DELETE RESTRICT,
  coverage_pct numeric(5,2) NOT NULL CHECK (coverage_pct BETWEEN 0 AND 100),
  as_of        date         NOT NULL DEFAULT CURRENT_DATE,
  CONSTRAINT uq_coverage UNIQUE (student_id, subject_id, as_of)
);

CREATE TABLE public.exam_readiness_score (
  id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id     uuid         NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  subject_id     uuid         NOT NULL REFERENCES public.subject(id)  ON DELETE RESTRICT,
  score          numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
  expected_marks numeric(6,2),
  as_of          date         NOT NULL DEFAULT CURRENT_DATE,
  CONSTRAINT uq_readiness UNIQUE (student_id, subject_id, as_of)
);

CREATE TABLE public.review_schedule (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id    uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  slo_id        uuid        NOT NULL REFERENCES public.slo(id)      ON DELETE RESTRICT,
  due_at        timestamptz NOT NULL,
  interval_days smallint    NOT NULL DEFAULT 1 CHECK (interval_days > 0),
  CONSTRAINT uq_review UNIQUE (student_id, slo_id)
);
CREATE INDEX ix_review_due ON public.review_schedule(student_id, due_at);

-- ============================================================================
-- 6. TUTOR SESSIONS                                             (tdd §5.3f)
--    Chat content is OWNER-ONLY: never visible to teacher, parent or admin.
-- ============================================================================

CREATE TABLE public.chat_session (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid        NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at   timestamptz
);
CREATE INDEX ix_chat_session_student ON public.chat_session(student_id, started_at DESC);

CREATE TABLE public.message (
  id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid         NOT NULL REFERENCES public.chat_session(id) ON DELETE CASCADE,
  role       message_role NOT NULL,
  content    text         NOT NULL,
  slo_refs   uuid[],      -- grounding citations (groundedness KPI)
  created_at timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX ix_message_session  ON public.message(session_id, created_at);
CREATE INDEX ix_message_slo_refs ON public.message USING gin (slo_refs);

CREATE TABLE public.visual_aid (
  id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid        NOT NULL REFERENCES public.message(id) ON DELETE CASCADE,
  kind       visual_kind NOT NULL,
  payload    jsonb       NOT NULL,   -- typed spec only; rendered sandboxed (LLM05)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_visual_aid_message ON public.visual_aid(message_id);

-- ============================================================================
-- 7. SECURITY & PLATFORM                                        (tdd §5.3g)
--    skill + mcp_server unified into agent_component so permission_manifest
--    can hold a single valid FK (no polymorphic reference).
-- ============================================================================

CREATE TABLE public.agent_component (
  id         uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
  kind       component_kind   NOT NULL,
  name       text             NOT NULL,
  source     text,
  version    text             NOT NULL,
  status     component_status NOT NULL DEFAULT 'submitted',
  created_at timestamptz      NOT NULL DEFAULT now(),
  updated_at timestamptz      NOT NULL DEFAULT now(),
  CONSTRAINT uq_component UNIQUE (kind, name, version)
);
CREATE TRIGGER trg_component_updated BEFORE UPDATE ON public.agent_component
  FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();

CREATE TABLE public.permission_manifest (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  component_id    uuid        NOT NULL UNIQUE REFERENCES public.agent_component(id) ON DELETE CASCADE,
  granted_scopes  text[]      NOT NULL DEFAULT '{}',
  db_scopes       text[]      NOT NULL DEFAULT '{}',
  network         jsonb       NOT NULL DEFAULT '{"default":"deny","allow":[]}'::jsonb,
  resource_limits jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.agent_sbom_entry (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  component_id uuid        NOT NULL UNIQUE REFERENCES public.agent_component(id) ON DELETE CASCADE,
  provenance   text,
  permissions  jsonb,
  content_hash text        NOT NULL,
  signature    text,
  admitted_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.vetting_result (
  id              uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
  component_id    uuid            NOT NULL REFERENCES public.agent_component(id) ON DELETE CASCADE,
  findings        jsonb,
  claim_vs_actual jsonb,
  verdict         vetting_verdict NOT NULL DEFAULT 'pending',
  created_at      timestamptz     NOT NULL DEFAULT now()
);
CREATE INDEX ix_vetting_component ON public.vetting_result(component_id, created_at DESC);

-- Security audit trail (tool calls + sensitive data access) -------------------
-- Partitioned table PKs must include the partition key.
CREATE TABLE public.audit_log (
  id         uuid        NOT NULL DEFAULT gen_random_uuid(),
  actor_id   uuid        REFERENCES public.app_user(id) ON DELETE SET NULL,
  action     text        NOT NULL,
  target     text,
  tool_call  jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE public.audit_log_default PARTITION OF public.audit_log DEFAULT;
CREATE INDEX ix_audit_actor ON public.audit_log(actor_id, created_at DESC);

-- Operational access log: EVERY API call, for the admin daily-logs panel (TEL-5)
CREATE TABLE public.api_request_log (
  id          bigint      GENERATED ALWAYS AS IDENTITY,
  request_id  uuid        NOT NULL,
  actor_id    uuid        REFERENCES public.app_user(id) ON DELETE SET NULL,
  role        user_role,
  method      text        NOT NULL,
  endpoint    text        NOT NULL,   -- route template, e.g. /api/tutor/ask
  path        text        NOT NULL,
  status_code smallint    NOT NULL,
  message     text,                   -- app error code, e.g. RATE_LIMITED
  latency_ms  integer,
  ip          inet,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE public.api_request_log_default PARTITION OF public.api_request_log DEFAULT;
CREATE INDEX ix_reqlog_day_endpoint ON public.api_request_log(created_at, endpoint, status_code);
CREATE INDEX ix_reqlog_day_status   ON public.api_request_log(created_at, status_code);
CREATE INDEX ix_reqlog_actor        ON public.api_request_log(actor_id, created_at DESC);

-- ============================================================================
-- End of initial schema.
-- Next migrations: RLS policies, reference seed data.
-- ============================================================================
