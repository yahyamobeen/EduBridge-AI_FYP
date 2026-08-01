# Technical Design Document
## EduBridge AI — A Secure, Agentic, Multilingual Learning Platform (Classes 9–12, PCTB & STBB)

**Version:** 0.2.0
**Status:** Draft — under section-by-section review
**Last Updated:** July 19, 2026
**Purpose:** Implementation-ready technical design derived from `prd.md`, for a curriculum-grounded, agentic, multimodal, multilingual tutoring + classroom-analytics platform with a Secure Skills & MCP Layer.
**Product Owner:** EduBridge AI Team (Group Leader: Yahya Mobeen) · **Supervisor:** Dr. Muhammad Arif Butt (FCIT, University of the Punjab)
**Source of truth:** `prd.md` (this TDD implements it) · **Upstream:** `EDUBRIDGE_AI_PROPOSAL.pdf`

> **Design approach:** *data-first / DB-led.* The data model (§5) is the backbone; component boundaries (§3), APIs (§7), and analytics are derived from it. Every design decision traces to a PRD requirement (`FR-`, `SEC-`, `NFR-`). Items marked **[PROPOSED — confirm]** are open decisions for review.

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-07-19 | EduBridge AI Team | Initial TDD draft derived from the accepted `prd.md`; matches supervisor TDD format, extended to engineering depth. Data-first (polyglot store + star-schema OLAP). |
| 0.1.1 | 2026-07-19 | EduBridge AI Team | Applied 15 critical-review fixes (§14); locked **Celery**; GPU/model-serving **mostly cloud**; added `api_request_log` + `fact_endpoint_calls` + admin **daily endpoint-logs** panel. |
| 0.2.0 | 2026-08-01 | EduBridge AI Team | OLTP moved to **Supabase**; **Supabase CLI migrations replace Alembic**; **Row Level Security** designed and implemented (§6.8). Schema: `class_level`, `subject_group`, `content_strategy`, `student_group`, `agent_component`; corrected `uuidv7()`→`gen_random_uuid()` (PG16) and the invalid partitioned-table PK on `audit_log`. Agent routing extended to **four content strategies** including **religious-verbatim** (generation disabled for Quran Translation). SQL now lives in `supabase/migrations/`. |

---

## 1. Context and Purpose

This document describes the technical design of **EduBridge AI**, a secure, agentic learning platform for Pakistani Classes 9–12 aligned to the Punjab (PCTB) and Sindh (STBB) boards. It converts the accepted PRD into an implementation-ready design: system architecture, module/component design, the **agent + skills + MCP** subsystem, a rigorous **data model** (relational OLTP + polyglot vector store + star-schema OLAP), the **Secure Skills & MCP Layer**, API contracts, deployment, and test strategy.

**Goal:** enable a student to ask curriculum questions in English/Urdu/Roman-Urdu (typed or spoken) and receive grounded, class-adaptive answers with retrieval-first visuals and an avatar; enable teachers/parents to run secure quizzes and read weak-area analytics; and enforce security/least-privilege across every agent skill and MCP server.

**Scope (tiers, from PRD §23):** **P0** — individual student tutor core (chatbot + visuals + avatar/voice) + baseline safety. **P1** — assessment, classroom, full Secure Skills & MCP Layer. **P2** — self-updating pipeline, breadth, stretch. This TDD designs the **full system** to implementation-ready depth, tagging tiers per component.

**Operational note (not a "warning" — this is a production system for minors):** the platform handles minors' data; self-hosting and least-privilege are first-class. Data about minors is minimized, isolated, and **never used to train models** (§5.9, §6). The class-based parental-consent gate (Classes 9–10 mandatory) is enforced at the data and API layers.

**Non-goals (PRD §2.4):** training foundation models; free-form diffusion image-gen (stretch); direct student↔teacher chat (stretch); boards beyond PCTB/STBB; native mobile app.

---

## 2. System Architecture

### 2.1 High-Level Architecture

EduBridge AI is a **modular monolith** (one FastAPI backend, clear internal module boundaries) with a Next.js frontend, MCP servers and model servers as separate processes, and a cross-cutting Secure Skills & MCP Layer. Three data stores: **Supabase / managed PostgreSQL** (OLTP source of truth, with Row Level Security), a **dedicated vector DB** (embeddings), and a **star-schema OLAP** schema (analytics) inside the same Supabase instance.

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER (Next.js/React/Tailwind)         │
│  Student/Teacher/Parent/Admin dashboards · Tutor chat (text+voice, EN/UR/   │
│  Roman-UR, RTL) · Sandboxed visual renderer (iframe+CSP+DOMPurify) · Avatar │
│  + audio player · Classroom & quiz UIs · next-intl i18n                     │
└───────────────────────────────────────────────────────────────────────────┘
             │ HTTPS (JWT)                                   ▲ SSE/stream
             ▼                                               │
┌───────────────────────────────────────────────────────────────────────────┐
│            APPLICATION LAYER — FastAPI modular monolith                     │
│  ┌──────────────── API Gateway: JWT auth · RBAC · Redis rate-limit (429) ─┐ │
│  │ Modules: auth · agent_orchestrator · retrieval(RAG) · assessment ·     │ │
│  │ classroom · curriculum_pipeline · reporting · platform                 │ │
│  │            │                                                            │ │
│  │            ▼   Agent Orchestrator (Qwen + LangGraph)  ── routes ──►     │ │
│  └────────────┼───────────────────────────────────────────────────────────┘ │
│               ▼                                                              │
│   ┌────────── SKILLS & MCP SUBSYSTEM ───────────┐   ┌── Async workers ──┐   │
│   │ Self skills: Curriculum-Retriever, Syllabus │   │ Celery/RQ:        │   │
│   │ Updater, Adaptive-Language, Visual-Renderer │   │ ETL, reports,     │   │
│   │ Audited MCP (separate procs): TTS/Avatar,   │   │ (re)indexing,     │   │
│   │ STT, OCR, Translation, Web-Search           │   │ mining, self-upd  │   │
│   └─────────────────────────────────────────────┘   └───────────────────┘   │
└───────────────────────────────────────────────────────────────────────────┘
     │                    │                        │                    │
     ▼                    ▼                        ▼                    ▼
┌─────────────┐  ┌──────────────────┐  ┌────────────────────┐  ┌──────────────┐
│ Supabase PG │  │  Vector DB       │  │ OLAP star schema   │  │ Redis        │
│ OLTP+RLS(SoT)│ │  Chroma/FAISS    │  │ (analytics schema) │  │ cache+RL+queue│
│ all domains │  │  BGE-M3 1024-dim │  │ facts/dimensions   │  │              │
└─────────────┘  └──────────────────┘  └────────────────────┘  └──────────────┘
        ▲  object storage (KB docs, textbook figures)
        │
┌───────────────────────────────────────────────────────────────────────────┐
│  MODEL SERVING (GPU): vLLM(Qwen) + hosted-API fallback · Whisper · BGE-M3/  │
│  reranker · Qwen2.5-VL(offline index) · Prompt Guard 2/Llama Guard 3 ·      │
│  Fish Audio S2 Pro (TTS) · MuseTalk (avatar)                                │
└───────────────────────────────────────────────────────────────────────────┘
╔═══════════════════════════════════════════════════════════════════════════╗
║  CROSS-CUTTING: SECURE SKILLS & MCP LAYER (OWASP-mapped)                    ║
║  vetting scanner · least-privilege manifests · sandbox · runtime guardrails ║
║  · AgentSBOM · audit log      |  DEVOPS: GitHub Actions CI/CD · Docker      ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

### 2.2 Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Backend framework** | FastAPI | ≥0.111 | Modular-monolith API, async |
| **ASGI server** | Uvicorn (+ Gunicorn workers) | ≥0.30 | Serving |
| **Language** | Python | ≥3.12 | Backend runtime |
| **OLTP database** | **Supabase** (managed PostgreSQL) | PG ≥15 | Source of truth (all domains), with Row Level Security |
| **Migrations** | **Supabase CLI** (versioned plain SQL in `supabase/migrations/`) | latest | Schema history, reviewable in PRs |
| **ORM / query layer** | SQLAlchemy 2.0 (hand-written models, no autogenerate) | latest | Typed access from FastAPI; schema authored in SQL |
| **Analytics (OLAP)** | Same Supabase instance, separate `analytics` schema | PG ≥15 | Star-schema facts/dimensions |
| **Vector database** | ChromaDB (primary) / FAISS (scale) **[PROPOSED]** | latest | ANN over BGE-M3 embeddings |
| **Cache / rate-limit / broker** | Redis | ≥7 | Cache, token-bucket, Celery broker |
| **Async jobs** | Celery (+ Redis broker) | latest | ETL, reports, indexing, mining, self-update, **request-log aggregation** |
| **Agent framework** | LangGraph + MCP SDK | latest | Agent graph + tool protocol |
| **Primary LLM** | Qwen2.5/Qwen3 (+Urdu LoRA), self-hosted via vLLM; hosted-API fallback | — | Orchestration/understanding/generation |
| **STT** | Whisper (large-v3 / Urdu fine-tune) | — | Speech-to-text |
| **Embeddings / rerank** | BGE-M3 (1024-dim) / BGE-reranker-v2-m3 | — | Cross-lingual retrieval + rerank |
| **Figure indexing** | Qwen2.5-VL (offline batch) | — | Index textbook figures |
| **Guardrails** | Prompt Guard 2 / Llama Guard 3 | — | Input/output safety (LLM01/05) |
| **TTS / avatar** | Fish Audio S2 Pro / MuseTalk v1.5 | — | Voice + lip-sync avatar |
| **Frontend** | Next.js + React + Tailwind; next-intl | Next ≥14 | Responsive web UI, i18n/RTL |
| **Safe rendering** | DOMPurify + sandboxed iframe + CSP; KaTeX, Mermaid, Chart.js/Recharts, function-plot | latest | Typed visual aids (LLM05) |
| **Auth** | JWT (access+refresh, python-jose); argon2/bcrypt (passlib) | latest | AuthN; strong password hashing |
| **Security tooling** | Semgrep, OPA/Rego, sigstore/cosign, container sandbox | latest | Vetting, policy, signing, isolation |
| **CI/CD & packaging** | GitHub Actions, Docker + docker-compose, uv | latest | Build/test/deploy, reproducible envs |

### 2.3 Architectural Decisions

- **AD-1 — Modular monolith + monorepo (T3).** One FastAPI app with strict module boundaries (`auth`, `agent`, `retrieval`, `assessment`, `classroom`, `pipeline`, `reporting`, `platform`, `security`); shared domain models; single repo. Rationale: an FYP team ships and reasons faster with one deployable; module boundaries preserve the option to split later. MCP servers and model servers run as **separate processes** (isolation + independent scaling of GPU work).
- **AD-2 — Data-first, polyglot storage (T6/T7/T8).** Supabase PostgreSQL is the **single source of truth**; the vector DB and the OLAP star schema are **derived** stores kept consistent by idempotent jobs (§5.6a). No business truth lives only in a derived store.
- **AD-6 — Supabase as database platform, application-managed auth.** Supabase provides managed PostgreSQL, RLS, and backups. **Supabase Auth (`auth.users`) is deliberately not used** — FastAPI issues its own JWTs and hashes passwords with argon2id (§3.1), keeping the auth design in application code. Consequence: RLS cannot use `auth.uid()`, so authorization context is passed per transaction (§6.8).
- **AD-7 — SQL-first schema.** The schema is authored as **plain SQL migrations** under `supabase/migrations/` (Supabase CLI), not generated from ORM models. Migrations are readable and reviewable in PRs; SQLAlchemy models are hand-written to match. This replaces Alembic autogeneration.
- **AD-3 — Self-host Qwen primary + hosted-API fallback (T4).** The agent LLM runs on self-hosted vLLM for privacy/cost; a hosted API is a circuit-breaker fallback for load/quality. Embeddings, rerank, and guardrails are always self-hosted; TTS/avatar hybrid.
- **AD-4 — Sync vs async boundary.** The request path (chat, quiz attempt, retrieval) is synchronous/streamed; heavy/periodic work (embedding (re)indexing, past-paper mining, weekly reports, OLAP ETL, self-update ingestion) runs on async workers. Nothing on the request path blocks on a batch job.
- **AD-5 — Security as a cross-cutting layer.** Every tool/skill/MCP call passes through the Secure Skills & MCP Layer (vetting at admission, guardrails at runtime); baseline guardrails + rate-limit ship in P0 (SEC-1/2/3).

### 2.4 Deployment Topology Options **[PROPOSED — confirm, T5]**

Self-hosting the Qwen agent + Whisper + BGE + guardrails + Fish S2 Pro + MuseTalk implies real GPU. Three options:

| Option | Where models run | App/DB | Pros | Cons |
|---|---|---|---|---|
| **A. On-prem GPU server (Recommended)** | University/lab GPU box (Docker) | Same box or a small server | Max privacy for minors' data; no recurring cloud cost; full control | Needs a capable GPU (VRAM); ops on the team; single-site availability |
| **B. Cloud GPU VM** | Cloud GPU instance | Same VM / managed DB | Elastic; no hardware to own; easy to scale for demos | Recurring cost; minors' data leaves premises (compliance care) |
| **C. Hybrid** | Models on a GPU box | App + DBs in a small cloud VM | Balances cost/privacy; app always-on | Two environments; network between app↔models |

**Recommendation:** GPU/model-serving is **mostly cloud-based** (user direction) — i.e. Qwen/Whisper/BGE/guardrails/TTS/avatar run on **cloud GPU instances** (Option B/C direction). The overall **deployment target remains open** (`[PROPOSED]`): the app/DB placement (co-located cloud vs on-prem) is still to be chosen; minors'-data handling for the cloud path is addressed in §5.9/§6.7. This decision affects §8 and model-serving topology only; the application and data design are identical across options.

---

## 3. Component Design

The backend is a modular monolith under `backend/app/<module>/`. Each module exposes a router (`routes.py`), a service layer (`service.py`), SQLAlchemy models (`models.py`), and schemas (`schemas.py`). Cross-module calls go through service interfaces, never direct DB access to another module's tables. Tier tags: **[P0]/[P1]/[P2]**.

### 3.1 Auth & RBAC — `backend/app/auth/` **[P0]**

**Responsibilities:** registration/login (JWT access+refresh), password hashing (argon2), role assignment, RBAC enforcement (dependency injectables), and the **class-based parental-consent gate** (Classes 9–10 require a verified `guardian_link`).

**Endpoints:**

| Method | Path | Auth | Role | Purpose |
|--------|------|------|------|---------|
| POST | `/api/auth/register` | No | — | Create student (board/class/medium); teacher/parent/admin variants |
| POST | `/api/auth/login` | No | — | Authenticate → access+refresh JWT |
| POST | `/api/auth/refresh` | Refresh JWT | any | Rotate access token |
| POST | `/api/auth/logout` | Yes | any | Revoke refresh token |
| POST | `/api/auth/guardian/invite` | Yes | Student | Invite a parent (email/code) to satisfy the 9–10 gate |
| POST | `/api/auth/guardian/confirm` | No (token) | Parent | Parent confirms link → `guardian_link.status=verified` |
| GET | `/api/auth/me` | Yes | any | Current identity + gate status |

**Key design decisions:**
- Passwords hashed with **argon2id** (never MD5 — the supervisor's template's MD5 is the explicit anti-pattern we avoid). Refresh tokens stored hashed, rotated, revocable.
- RBAC via FastAPI dependencies: `require_role(...)`, `require_subject_scope()`, `require_guardian_verified()`. The gate dependency blocks **every student learning/assessment endpoint** for a Class 9–10 student whose `guardian_link` is not `verified` — `/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, and `/api/reports/*` (returns `403 GATE_PENDING`). An authz-matrix test asserts the gate on each such route (§9.4).
- **Anti-forgery of the gate:** `guardian_link` has `CHECK(parent_id≠student_id)`; the service enforces `parent_id.role='parent'` and requires a distinct **out-of-band** verification signal (a parent email/identity separate from the student's session) before `status→verified` — a student cannot self-satisfy the gate.
- **Single canonical parent↔child link:** `guardian_link` is the only source of truth for "a parent may view a child" and for the gate; the guardian-space path (§3.6) creates/verifies a `guardian_link`, it does not rely on `enrollment`.
- **Enforcement is at the API + data layer**, not the UI, so it cannot be bypassed by calling the API directly (security gate #4).
- **RLS context is set per transaction.** Because auth is application-managed, every request transaction issues `SET LOCAL app.current_user_id = '<uuid>'` before any query, which the RLS policies read (§6.8). If it is not set, policies deny everything — fail-closed.
- **Student registration captures `student_group`** alongside board/class/medium; a database `CHECK` rejects invalid class/group pairs (e.g. a Class-9 student marked `pre_medical`).

**Interfaces:** `AuthService.register()`, `.login()`, `.rotate_refresh()`, `GuardianService.invite()/confirm()/is_verified(student_id)`.

### 3.2 Agent Orchestrator — `backend/app/agent/` **[P0]**

**Responsibilities:** run the LangGraph agent (Qwen): parse the query (subject/class/board/task/language), enforce input guardrail + rate-limit, route Branch A/B, call skills, ground generation, decide visuals, output guardrail, stream the answer, and drive TTS/avatar. Full graph in §4.

**Endpoints:**

| Method | Path | Auth | Role | Purpose |
|--------|------|------|------|---------|
| POST | `/api/tutor/ask` | Yes | Student (gate-verified) | Text/voice question → streamed grounded answer (SSE) |
| POST | `/api/tutor/explain-step` | Yes | Student | Expand a specific solution step (FR-1) |
| GET | `/api/tutor/sessions/{id}` | Yes | Student (owner) | Retrieve own chat session |

**Key design decisions:**
- The orchestrator is a **LangGraph state machine** (nodes = guardrail, parse, route, retrieve, generate, visual, guard-out, speak). State is typed; each node is independently testable (NFR-6).
- Every tool/skill call is wrapped by the Secure Skills & MCP Layer client (§6); the orchestrator never calls a skill directly.
- Streaming via SSE; the avatar/audio are produced after text is finalized (§3.7).
- **Grounding guard:** if retrieval is below the similarity threshold, the node returns a "no confident curriculum-grounded answer" result rather than free-generating (PRD §20).

**Interfaces:** `AgentGraph.run(query_ctx) -> stream`, node callables, `ToolClient.call(skill, args)` (vetted).

### 3.3 Skills & MCP Subsystem — `backend/app/skills/`, `backend/app/mcp/` **[P0 self-skills / P1 full MCP]**

**Responsibilities:** implement self-created skills and integrate audited third-party skills/MCP servers behind a uniform **skill contract**; every call brokered by the Secure Skills & MCP Layer.

**Skills registry:**

| Skill | Type | Tier | Purpose |
|---|---|---|---|
| `curriculum_retriever` | self | P0 | Cross-lingual retrieve + rerank over KB (Branch A) / Urdu corpus (Branch B) |
| `adaptive_language` | self | P0 | Adjust vocabulary to class level; generate-in-Urdu + glossary |
| `visual_renderer` | self | P0 | Produce typed visual spec (KaTeX/Mermaid/chart-JSON/function-plot) |
| `syllabus_updater` | self | P2 | Trigger/curate self-update ingestion |
| `tts_avatar` (Fish S2 Pro + MuseTalk) | MCP | P0 | Speech + lip-synced avatar |
| `stt` (Whisper) | MCP | P0 | Speech-to-text |
| `ocr` | MCP | P1 | OCR for figure captions/notes |
| `translation` | MCP | P1 | Support glossary/edge cases |
| `web_search` | MCP | P2 | Restricted, vetted external lookups |

**Key design decisions:**
- **Uniform skill contract:** `name`, JSON input/output schema, declared capabilities/permissions (drives the manifest, §6). MCP servers run as **separate processes** (sandbox boundary).
- Third-party skills/MCP are **admitted only via vetting** (claim-vs-actual + AgentSBOM). `web_search` is least-privilege and P2 (highest injection risk).

**Interfaces:** `Skill.invoke(input) -> output`; `MCPClient.call(server, tool, args)`; registry `get_skill(name)`.

### 3.4 Retrieval / RAG — `backend/app/retrieval/` **[P0]**

**Responsibilities:** cross-lingual retrieval + reranking, Branch A/B routing, grounding context assembly, and the vector-store↔Postgres consistency contract (read side).

**Key design decisions:**
Routing is driven by the subject's **`content_strategy`** column (four values), not by a hard-coded subject name:

- **`branch_a_english_source`** (Maths, Physics, Chemistry, Biology, Computer Science, Islamiat, Pakistan Studies): embed query (BGE-M3) → ANN over the vector DB collection filtered by `board/class/subject/chapter` + live KB version → rerank (BGE-reranker-v2-m3) → assemble grounded context (English source) → hand to `adaptive_language` for generate-in-Urdu.
- **`branch_b_urdu_native`** (Urdu): retrieve from the Urdu-notes collection; objective items returned **verbatim**, productive items via template scaffold.
- **`english_language`** (English): retrieve from the English-subject corpus; grammar/essay/comprehension answered against fixed exam templates.
- **`religious_verbatim`** (Quran Translation): retrieval **only**. The generation node is skipped entirely; the stored board-approved text is returned word-for-word with its reference. A retrieval miss returns an explicit "not found", never a generated answer (FR-17).
- Every vector hit carries the **Postgres `curriculum_item`/`urdu_note_item` id**; the actual grounded text is read from Postgres (source of truth), not from the vector payload (avoids drift #2).
- **Similarity threshold** gates whether to answer, render a visual, or degrade (PRD §20).

**Interfaces:** `Retriever.search(query, filters) -> [hit]`, `Retriever.rerank(hits)`, `Grounder.assemble(hits) -> context`.

### 3.5 Assessment — `backend/app/assessment/` **[P1]**

**Responsibilities:** quiz build (teacher or agent-draft), secure delivery, auto-grading, adaptive difficulty, past-paper-frequency selection, and feeding the analytics layer (BKT/IRT). Heavy computation (mining, calibration, mastery updates) runs in async workers → OLAP (§5.6).

**Endpoints:**

| Method | Path | Auth | Role | Purpose |
|--------|------|------|------|---------|
| POST | `/api/quiz` | Yes | Teacher (subject) | Create quiz (subject/topic tags); optional agent-draft |
| POST | `/api/quiz/{id}/publish` | Yes | Teacher | Open a time-boxed window |
| POST | `/api/quiz/{id}/attempts` | Yes | Student (enrolled) | Start an attempt (server issues shuffled items) |
| POST | `/api/quiz/attempts/{id}/answer` | Yes | Student (owner) | Submit an answer (key checked server-side) |
| POST | `/api/quiz/attempts/{id}/submit` | Yes | Student (owner) | Submit/auto-submit → grade |
| GET | `/api/practice/adaptive` | Yes | Student | Adaptive practice from high-frequency SLOs (FR-3/15) |

**Key design decisions:**
- **Answer keys never leave the server** (NFR-8); the attempt API returns only items + choices. Grading is server-side; `attempt_answer.correct` computed on submit.
- Adaptive difficulty uses **IRT**-calibrated item difficulty + current mastery to pick the next item; frequency selection uses `slo_frequency_cluster`.
- Attempt lifecycle is a **state machine** (§5.8) with one attempt, shuffle, time-box + auto-submit.

**Interfaces:** `QuizService.build()/publish()`, `AttemptService.start()/answer()/submit()`, `ItemSelector.next(student, quiz)`.

### 3.6 Classroom & Spaces — `backend/app/classroom/` **[P1]**

**Responsibilities:** spaces, revocable join codes, enrollment (consent), subject-scoped teacher views, parent all-subject read-only links, announcements, and quiz report exposure.

**Endpoints:**

| Method | Path | Auth | Role | Purpose |
|--------|------|------|------|---------|
| POST | `/api/spaces` | Yes | Teacher/Parent | Create space (teacher declares subject) |
| POST | `/api/spaces/{id}/join-code` | Yes | Owner | Generate/rotate/revoke join code |
| POST | `/api/spaces/join` | Yes | Student | Join via code (consent) |
| DELETE | `/api/spaces/{id}/membership` | Yes | Student | Leave space anytime |
| GET | `/api/spaces/{id}/report` | Yes | Teacher(subject)/Parent(child) | Weak-area report (scoped) |
| POST | `/api/spaces/{id}/announcements` | Yes | Owner | Post one-way announcement |

**Key design decisions:**
- **Consent = joining.** Enrollment row is the consent record; students see viewers and can leave (sets `enrollment.left_at`).
- **Least-privilege scoping enforced in queries:** teacher report queries join through **`teacher_subject_scope`** (M:N) so a teacher sees only the subjects (per board×class) they actually teach; parent queries filter by **`guardian_link`**. Enforced in the service/data layer, never trusting the client.
- **Single parent-link source of truth:** the guardian-space join path **creates/verifies a `guardian_link`** — parent visibility and the 9–10 gate never depend on `enrollment` (avoids the dual-mechanism gap).
- Reports are **read from the OLAP star schema** (§5.6), not recomputed on the request path.

### 3.7 Multimodal — `backend/app/multimodal/` **[P0]**

**Responsibilities:** the visual-aid decision ladder, safe rendering contract, TTS/avatar, and STT.

**Key design decisions:**
- **Visual ladder:** retrieve indexed `textbook_figure` → else emit a **typed** visual spec (KaTeX/Mermaid/chart-JSON/function-plot) → else curated image → else text. The backend emits only a **typed spec + kind**; the **frontend renders it sandboxed** (iframe + CSP + DOMPurify) — no raw HTML/JS crosses the boundary (SEC-2/LLM05).
- **TTS/avatar** via the `tts_avatar` MCP: text → Fish S2 Pro audio → MuseTalk lip-sync. Consent required for any cloned voice. **Urdu fallback** to ur-PK/local Urdu TTS on low quality (PRD §20).
- **STT** via Whisper MCP; low-confidence → ask user to confirm.

**Interfaces:** `VisualDecider.decide(context) -> VisualSpec`, `TTSAvatar.speak(text, lang) -> media`, `STT.transcribe(audio) -> text`.

### 3.8 Curriculum Pipeline — `backend/app/pipeline/` **[P2]**

**Responsibilities:** the self-updating KB — detect new board syllabi/textbooks, **provenance-check**, parse/index into a new `kb_document` **board+year version**, verify integrity, and (re)generate embeddings; quarantine on failure. Runs entirely in async workers.

**Key design decisions:**
- **Provenance gate:** a source is ingested only after signature/authenticity check (FR-12/SEC-9). Failures → `kb_document.provenance_status=quarantined` + admin alert; **never auto-ingested**.
- New content creates a **new version**, not an in-place overwrite (lineage + rollback). Figure indexing uses Qwen2.5-VL offline. Embedding (re)index triggers vector-store sync (§5.6a).

**Interfaces:** `IngestJob.run(source)`, `ProvenanceChecker.verify(source)`, `Indexer.index(kb_document)`.

### 3.9 Platform (Gateway, Rate-limit, Reporting jobs) — `backend/app/platform/`, `backend/app/reporting/` **[P0 rate-limit / P1 reporting]**

**Responsibilities:** API-gateway concerns (JWT verify, RBAC, request IDs), **Redis token-bucket + sliding-window rate-limiting** (per user/IP → 429), **per-request access logging** (`api_request_log`), and the reporting/ETL job definitions that refresh the OLAP layer.

**Key design decisions:**
- Rate-limit middleware runs before the agent (SEC-3/LLM10); limits + quotas configurable by Admin; returns `429` with `Retry-After`. **Per-user** limits apply within authenticated sessions; **per-IP** limits are **institution-aware** — higher, configurable ceilings for known institution egress IPs (whole schools share one NAT'd IP, so a strict per-IP bucket would self-DoS a class); strict per-IP applies mainly to unauthenticated traffic.
- Jobs are **Celery beat** schedules: reporting/ETL (weekly report, class weak-areas, exam-readiness) materialize read-models (§5.6); a **quiz auto-submit sweeper** grades `in_progress` attempts past `time_close`; the request path only reads.
- **Request-logging middleware** records **every** API call — `method, endpoint, status_code, message, latency_ms, actor_id, request_id, ip` — to `api_request_log` (async/buffered write, off the hot path so it never adds request latency). A daily Celery job rolls it up into `fact_endpoint_calls`; the **admin daily-logs panel** reads per-day logs + aggregates via `GET /api/admin/logs/endpoints` (§7). This is **operational** logging, distinct from the security `audit_log` (§6.7).

### 3.10 Frontend — `frontend/` (Next.js) **[P0→P1]**

**Responsibilities:** role dashboards, tutor chat (text+voice, streaming), sandboxed visual renderer, avatar/audio player, classroom/quiz UIs, i18n (EN/UR/Roman-Urdu) with **RTL**.

**Key design decisions:**
- **Sandboxed visual renderer** component: renders the typed visual spec inside an `<iframe sandbox>` with a strict CSP; any string is passed through **DOMPurify**. This is the frontend half of LLM05.
- `next-intl` for locales; RTL layout for Urdu; accepts Urdu script + Roman-Urdu input.
- Auth tokens in httpOnly cookies; role-gated routes; the parental-gate state drives an onboarding wall for Class 9–10.

### 3.11 Data Flows

**(1) Runtime tutor flow (9 steps) —** `POST /api/tutor/ask`:
```
Student(text|voice) → [gateway: JWT+RBAC+rate-limit(429?)] → [STT:Whisper if voice]
 → parse(subject/class/board/lang) → [input guardrail: PromptGuard/LlamaGuard]
 → route(Branch A: BGE-M3 xling retrieve+rerank over KB | Branch B: Urdu corpus)
 → ground(read text from Postgres by hit ids) → generate(Qwen, generate-in-Urdu+glossary | template)
 → visual decision(figure? else typed spec) → [output guardrail: LlamaGuard]
 → stream text + sandboxed visual → TTS(Fish S2 Pro) → avatar(MuseTalk) → persist chat_session/message
```
Failure branches: rate-limit→429; guardrail block→safe refusal; retrieval miss→"no grounded answer"; TTS low-Urdu→fallback voice; render fail→curated→text.

**(2) Quiz lifecycle —** create→publish→attempt(shuffled, keys server-side)→answer→submit/auto-submit→grade→OLAP update→teacher report. State machine §5.8.

**(3) Enrollment/consent —** teacher/parent create space→share join code→student joins (consent, `enrollment`)→viewer read-only→student may leave.

**(4) Self-update ingestion —** detect→provenance check→(quarantine|parse)→index new board+year version→integrity verify→embed→vector sync→live.

**(5) Skill/MCP vetting —** submit→scan+claim-vs-actual→(block|manifest)→sandbox→admit+AgentSBOM→runtime guardrails→(suspend on violation). Detail §6.

---

## 4. Agent, Skills & MCP Design

*(This is the core novel subsystem — it occupies the section slot the supervisor's template used for "Vulnerability Design", inverted to constructive design.)*

### 4.1 Agent state (LangGraph)

The orchestrator is a typed LangGraph graph. State:

```python
class TutorState(TypedDict):
    session_id: UUID
    raw_input: str            # text or STT output
    is_voice: bool
    language: Literal["en","ur","roman_ur"]
    subject: str; klass: int; board: Literal["PCTB","STBB"]; task: str
    guard_in: GuardVerdict    # allow | block(reason)
    route: Literal["A","B"]
    hits: list[RetrievalHit]  # carry Postgres ids
    grounded: bool
    context: str              # text read from Postgres (SoT)
    answer: str
    visual: VisualSpec | None
    guard_out: GuardVerdict
    media: MediaRef | None    # tts+avatar
    degrade: str | None       # reason if degraded
```

### 4.2 Graph nodes & edges

```
[stt?]──▶[parse]──▶[guard_in]──block──▶[safe_refusal]──▶END
   ▲(voice)            │allow
                       ▼
                    [route]──A──▶[retrieveA]─▶[rerank]─┐
                       │                                ├▶[ground]──miss──▶[degrade]──▶END
                       └──B──▶[retrieveB]──────────────┘   │hit
                                                            ▼
                                          [generate]──▶[visual]──▶[guard_out]
                                             block◀──────────────────┘
                                             │allow
                                             ▼
                                   [speak(tts+avatar)]──▶[persist]──▶END
```
- Every retrieve/generate/speak node calls a skill **only** via the vetted `ToolClient` (§6). Nodes are pure/testable; the graph is deterministic given state (NFR-6).
- `guard_in`/`guard_out` are Prompt Guard 2 / Llama Guard 3 (SEC-1/2). `degrade` implements PRD §20 fallbacks. A `guard_out` **block** routes to `safe_refusal`/`degrade` with a **max-1 regeneration retry** — the block→generate edge is bounded (no infinite loop).

### 4.3 Skill contract & tool schema

Every skill (self or MCP) implements a uniform contract; the declared `capabilities` drive its least-privilege manifest (§6):

```json
{
  "name": "curriculum_retriever",
  "version": "1.2.0",
  "input_schema":  {"query":"str","board":"enum","class":"int","subject":"str","branch":"A|B","k":"int"},
  "output_schema": {"hits":[{"item_id":"uuid","score":"float","slo_ids":["uuid"]}]},
  "capabilities": ["vector_db:read","postgres:read:curriculum"],
  "network": "none"
}
```

### 4.4 Self-created skills

- **`curriculum_retriever`** — BGE-M3 embed → ANN (vector DB, metadata-filtered) → BGE-reranker; returns hit ids only (text read from Postgres).
- **`adaptive_language`** — sets reading level by `class`; **generate-in-Urdu** grounded in retrieved English text + `glossary_term` lookups (not post-translation, FR-7).
- **`visual_renderer`** — emits a **typed** `VisualSpec` (`kind ∈ {katex,mermaid,chart,functionplot}` + payload); never raw HTML.
- **`syllabus_updater`** — orchestrates provenance-checked ingestion (P2, §3.8).

### 4.5 MCP client/server design

- Audited third-party capabilities (TTS/avatar, STT, OCR, translation, web-search) run as **separate MCP server processes**; the backend is an **MCP client**. Transport: stdio/local socket within the sandbox; no direct DB access.
- Each server is admitted only through vetting (§6) with an AgentSBOM entry and a permission manifest; `web_search` (P2) gets the tightest network allowlist (prompt-injection surface, LLM01).

### 4.6 Routing, grounding & anti-hallucination

- **Route:** read `subject.content_strategy` and dispatch to one of the four paths in §3.4. **`religious_verbatim` disables the generate node** — a hard guard, not a prompt instruction, so the model cannot compose Quranic text under any circumstance.
- **Grounding rule:** the generator receives only retrieved, Postgres-sourced context; if max rerank score < `τ_sim` **[PROPOSED threshold]**, the graph goes to `degrade` (no free-generation). Objective Urdu items are returned **verbatim**; productive items use a controlled template.
- **Citations:** answers carry the `curriculum_item`/`slo` ids used, enabling the groundedness KPI (PRD §22).
- **Indirect-injection defense (LLM01):** retrieved KB text, figure OCR, and tool/`web_search` outputs are **delimited/spotlighted and sanitized** — treated as untrusted *data*, never as instructions — before entering the generator prompt. Guardrails thus cover input **and** grounding content, not just user input and final output.

---

## 5. Data Design — Design Backbone

The data model leads the design. PostgreSQL (OLTP) is the **single source of truth**; the vector DB (§5.5) and OLAP star schema (§5.6) are **derived** and reconciled by jobs (§5.6a).

### 5.1 Data architecture principles

- **Normalization:** 3NF baseline in OLTP; denormalization only in the OLAP layer (§5.6).
- **Keys:** surrogate PKs `uuid` via **`gen_random_uuid()`** (built into PG 13+); natural **unique constraints** for real-world keys (`app_user.email`, `join_code.code`, `slo(chapter_id,code)`). *`uuidv7()` is only available from PostgreSQL 18 — switch the defaults there for time-ordered keys and better index locality.*
- **Referential integrity:** every FK declared with an explicit `ON DELETE` rule (`RESTRICT` for curriculum/audit; `CASCADE` only for owned children; `SET NULL` where optional). No application-only relationships.
- **Enums/domains:** status/category columns use Postgres `ENUM` or lookup tables (no free-text status).
- **Auditing:** every table has `created_at`, `updated_at` (UTC, trigger-maintained); mutable domain tables carry `created_by`. Sensitive deletes are **soft** (`deleted_at`) where retention/audit requires it.
- **Tenancy/consent scoping:** classroom data scoped by `space_id`; a student's analytics visibility is mediated by `enrollment`/`guardian_link` (never a raw join without the scope predicate).
- **Concurrency:** `version int` optimistic-lock column on quiz attempts and mastery rows.
- **Minors' data:** PII columns tagged and isolated (§5.9); chat content is owner-only.

### 5.2 Conceptual ER model (cardinalities)

```
user ─1:1─ {student|teacher|parent|admin}_profile
parent_profile ─M:N─ student_profile          (via guardian_link; status)
teacher_profile ─1:N─ classroom_space ─M:N─ student_profile (via enrollment)
classroom_space ─1:N─ join_code ; ─1:N─ announcement
board ─1:N─ class_level ─1:N─ subject ─1:N─ chapter ─1:N─ slo
subject ─1:N─ subject_group          (which elective groups take the subject)
student_profile ──student_group──▶ subject_group  (a student's subject list)
curriculum_item ─M:N─ slo ; ─N:1─ chapter ; ─1:0..1─ textbook_figure
kb_document ─1:N─ curriculum_item|urdu_note_item   (versioned by board+year)
past_paper ─1:N─ question ─M:N─ slo ; question ─1:1─ item_difficulty
quiz ─1:N─ quiz_attempt ─1:N─ attempt_answer ─N:1─ question
student_profile ─1:N─ mastery_estimate ─N:1─ slo
student_profile ─1:N─ coverage_record | exam_readiness_score | review_schedule
chat_session ─1:N─ message ─1:0..1─ visual_aid
agent_component ─1:1─ permission_manifest ; ─1:1─ agent_sbom_entry ; ─1:N─ vetting_result
question ─1:1─ question_key   (server-only; no RLS policy grants access)
* ─writes─▶ audit_log
```

### 5.3 Logical schema by domain

Each table lists notable columns, keys, and indexes (full DDL for core tables in §5.4; remaining tables follow the same conventions).

- **(a) Identity & RBAC:** `app_user(id, email🔑, password_hash, role⋈enum, status, ts)` *(table name `app_user`; "user" is reserved in Postgres)*, `student_profile(user_id🔗, board, class_level, **student_group**, medium, language_pref, CHECK class/group pairing)`, `teacher_profile(user_id🔗)`, `teacher_subject_scope(teacher_id🔗, subject_id🔗, PK(teacher_id,subject_id))` — **explicit M:N**: report scoping joins through this (a subject is per board×class, §b), `parent_profile(user_id🔗)`, `admin_profile(user_id🔗, scope)`, `guardian_link(parent_id🔗, student_id🔗, status⋈enum, verification_method, verified_at, CHECK(parent_id≠student_id), UNIQUE(parent_id,student_id))`, `auth_token(id, user_id🔗, kind, hash, revoked, expires_at)`.
- **(b) Curriculum & KB:** `board`, `class_level(board_id🔗, level 9..12, UNIQUE(board_id,level))`, `subject(class_level_id🔗, name, **content_strategy**⋈enum, UNIQUE(class_level_id,name))` — defined **once per (board,class)**, never per group, `subject_group(subject_id🔗, student_group⋈enum, PK(subject_id,student_group))` — which elective groups take it, `chapter(subject_id🔗, no, title)`, `slo(chapter_id🔗, code, text, effective_from_year, retired_at, UNIQUE(chapter_id,code))` — **soft-retired, never deleted**, `kb_document(id, board_id🔗, curriculum_year, source_uri, provenance_status⋈enum, version, integrity_hash, UNIQUE(board_id,curriculum_year,version))`, `curriculum_item(id, kb_document_id🔗, chapter_id🔗, exercise, question, worked_solution, lang)`, `curriculum_item_slo(item_id🔗, slo_id🔗, PK(item_id,slo_id))`, `textbook_figure(id, curriculum_item_id🔗?, chapter_id🔗, caption_ocr, embedding_ref)`, `urdu_note_item(id, kb_document_id🔗, type⋈enum, fields jsonb, source)`, `glossary_term(id, board_id🔗, subject_id🔗, en_term, ur_term, UNIQUE(subject_id,en_term))`.
- **(c) Assessment:** `past_paper(id, board_id🔗, class, subject_id🔗, year)`, `question(id, past_paper_id🔗?, stem, choices jsonb, primary_slo_id🔗, UNIQUE)` — **no key column here**, `question_key(question_id🔗🔑, answer_key, rationale)` — **server-only table, never in any client schema/route** (NFR-8 backstop), `question_slo(question_id🔗, slo_id🔗, is_primary, PK(...))`, `item_difficulty(question_id🔗🔑, irt_a, irt_b, irt_c)`, `slo_frequency_cluster(id, slo_id🔗, board_id🔗, freq_score, years)`, `quiz(id, space_id🔗, subject_id🔗, created_by🔗, source⋈enum, time_open, time_close, one_attempt=true, shuffle=true)`, `quiz_question(quiz_id🔗, question_id🔗, PK(...))`, `quiz_attempt(id, quiz_id🔗, student_id🔗, state⋈enum, started_at, submitted_at, score, version, UNIQUE(quiz_id,student_id))`, `attempt_answer(id, attempt_id🔗, question_id🔗, response, correct)`.
- **(d) Learner analytics (OLTP current-state):** `mastery_estimate(student_id🔗, slo_id🔗, p_mastery, p_transit, p_guess, p_slip, updated_at, version, PK(student_id,slo_id))`, `coverage_record(id, student_id🔗, subject_id🔗, coverage_pct, as_of)`, `exam_readiness_score(id, student_id🔗, subject_id🔗, score, expected_marks, computed_at)`, `review_schedule(id, student_id🔗, slo_id🔗, due_at, interval)`.
- **(e) Classroom:** `classroom_space(id, owner_id🔗, owner_role, subject_scope, status)`, `join_code(id, space_id🔗, code🔑, revoked, expires_at)`, `enrollment(id, space_id🔗, student_id🔗, joined_at, left_at, UNIQUE(space_id,student_id))`, `announcement(id, space_id🔗, author_id🔗, body, ts)`.
- **(f) Tutor:** `chat_session(id, student_id🔗, started_at)`, `message(id, session_id🔗, role, content, slo_refs uuid[], ts)`, `visual_aid(id, message_id🔗, kind⋈enum, payload jsonb, sandboxed=true)`.
- **(g) Security & platform:** `agent_component(id, kind⋈enum{skill,mcp_server}, name, source, version, status⋈enum, UNIQUE(kind,name,version))` — **skill and mcp_server unified into one table** so `permission_manifest` can hold a single valid FK (a polymorphic reference to two tables is not expressible), `permission_manifest(id, component_id🔗 UNIQUE, granted_scopes text[], db_scopes text[], network jsonb, resource_limits jsonb)`, `agent_sbom_entry(id, component_id🔗, provenance, permissions jsonb, hash, admitted_at)`, `vetting_result(id, component_id🔗, findings jsonb, claim_vs_actual jsonb, verdict⋈enum, ts)`, `audit_log(id, actor_id🔗?, action, target, tool_call jsonb, ts)` — security trail, `api_request_log(id, request_id, actor_id🔗?, method, endpoint, path, status_code, message, latency_ms, ip, ts)` — **operational per-call access log (daily-partitioned; admin daily-logs panel)**, (`rate_limit_bucket` → Redis).

### 5.4 Physical design & DDL

> **The authoritative schema lives in `supabase/migrations/` — not in this document.**
> Duplicating DDL here would guarantee drift. This section describes the *approach*; the SQL is the artefact.

| Migration | Contents |
|---|---|
| `20260801120000_initial_schema.sql` | Extensions, enums, all 42 tables, constraints, indexes, triggers, partitions |
| `20260801120100_rls_policies.sql` | `app_backend` role, RLS helper functions, 54 policies (§6.8) |
| `20260801120200_seed_reference_data.sql` | Boards, class levels, subjects (76 rows) and elective-group mappings |

**Conventions applied throughout:**

- **Primary keys** — `uuid DEFAULT gen_random_uuid()` (PG 13+). `bigint GENERATED ALWAYS AS IDENTITY` for the high-volume `api_request_log`.
- **Referential integrity** — every FK declares `ON DELETE`: `RESTRICT` for curriculum and audit references, `CASCADE` for owned children, `SET NULL` for optional actors.
- **Enums** for every status/category column; no free-text status anywhere.
- **Check constraints** encode real rules: `class_level BETWEEN 9 AND 12`, `parent_id <> student_id` on the parental gate, class/group pairing, `time_close > time_open`, probability columns bounded `0..1`.
- **Natural uniqueness** — `app_user.email`, `join_code.code`, `slo(chapter_id,code)`, `quiz_attempt(quiz_id,student_id)` (enforces one attempt), `subject(class_level_id,name)`.
- **Index strategy** — every FK used in a join or filter; **partial indexes** for hot predicates (`WHERE status='verified'`, `WHERE state='in_progress'` for the auto-submit sweeper, `WHERE left_at IS NULL`); **GIN** on `jsonb` and `uuid[]` (`message.slo_refs`, `question.choices`).
- **Partitioning** — `audit_log` (monthly) and `api_request_log` (daily) are range-partitioned on `created_at`, each with a `DEFAULT` partition so inserts never fail. Note that a partitioned table's primary key **must include the partition key**, hence `PRIMARY KEY (id, created_at)`. `message` is intentionally left unpartitioned for now so `visual_aid` can keep a simple single-column FK.
- **Triggers** — a shared `app.set_updated_at()` maintains `updated_at` on every mutable table.

**Two corrections made against earlier drafts of this document:**

1. `uuidv7()` does not exist before **PostgreSQL 18**; on the targeted version it fails outright. Replaced with `gen_random_uuid()`.
2. `audit_log` was specified with `id uuid PRIMARY KEY` while partitioned by `created_at` — rejected by PostgreSQL. Corrected to a composite key.

### 5.5 Vector store design (polyglot)

Dedicated vector DB (**ChromaDB primary; FAISS for scale — [PROPOSED]**). One **collection per domain**, each vector's payload carries the **Postgres id** (join key) + filter metadata:

| Collection | Source table | Embedded text | Payload (filter) metadata |
|---|---|---|---|
| `kb_items` | `curriculum_item` | question + solution | item_id, board, class, subject, chapter, slo_ids, lang, kb_version |
| `figures` | `textbook_figure` | caption_ocr | figure_id, chapter, slo_ids, kb_version |
| `urdu_notes` | `urdu_note_item` | note text | note_id, type, chapter, kb_version |
| `chat` (optional) | `message` | student turns | session_id, student_id, slo_refs |

- **Model:** BGE-M3, **1024-dim**, cosine; **HNSW** index. Query = embed → ANN top-k with metadata filter → return ids → **read grounded text from Postgres** (never trust payload text as truth).
- **Active-version pinning (fixes edition mixing):** every `kb_items`/`figures`/`urdu_notes` query filters `kb_version = live version` (from `kb_document.is_live`, §5.4), so a version bump never returns a mix of curriculum years.
- **Owner-only chat:** the `chat` collection is queried **only with a `student_id` equality filter** — no cross-student retrieval of minors' chat (§5.9).
- **Write path:** on `curriculum_item`/`urdu_note_item`/`textbook_figure` insert/update, or a `kb_document` version bump/flip-to-live, an async **(re)index job** upserts vectors keyed by Postgres id and **retires** superseded-version vectors.

### 5.6 Analytics & measurement layer (star schema / OLAP)

A dedicated `analytics` schema (separate from OLTP), refreshed by ETL jobs; all reports/dashboards read here.

**Dimensions:** `dim_student`, `dim_slo`, `dim_subject`, `dim_chapter`, `dim_board`, `dim_class`, `dim_question`, `dim_date`, `dim_endpoint`.
**Facts:**

| Fact | Grain | Measures |
|---|---|---|
| `fact_quiz_attempt` | student × question × attempt | correct, response_time, difficulty(IRT) |
| `fact_mastery_snapshot` | student × slo × date | p_mastery (BKT), delta |
| `fact_coverage` | student × subject × date | coverage_pct |
| `fact_chat_interaction` | student × slo × date | question_count (weak-signal) |
| `fact_exam_readiness` | student × subject × date | readiness_score, expected_marks |
| `fact_attempt_slo` | student × slo × date | wrong_count, attempts, weight |
| `fact_endpoint_calls` | endpoint × status × date | call_count, error_count, p95_latency (feeds the admin **daily endpoint-logs** panel) |

**SLO attribution rule (FR-11 correctness):** each `question` has a `primary_slo_id`; a wrong answer credits the primary SLO by 1, or is **fractionally allocated** across its `question_slo` set (Σ weights = 1) — never double-counted or dropped. Weak-area rankings and `study_next` read from `fact_attempt_slo` (student×SLO grain), not from the student×question `fact_quiz_attempt`.

**Measurement logic (DS core):**
- **BKT** per SLO: `P(L_t) = P(L_{t-1}) + (1−P(L_{t-1}))·P(T)`; observation likelihood uses guess/slip; mastery **decays** between sessions; `review_schedule` implements spaced repetition.
- **IRT** calibrates `item_difficulty` from past-paper miss-rates (offline job).
- `exam_readiness = Σ_slo (mastery × frequency)`; `study_next` ranks SLOs by `frequency × (1 − mastery)`.

### 5.6a Data integration & consistency (three stores)

- **OLTP → vector:** entity write / `kb_document` version bump enqueues an idempotent (re)index job (keyed by Postgres id + `kb_version`). A new edition becomes servable only after `lifecycle` reaches `integrity_verified`; an explicit **flip-to-live** sets `is_live` (superseding the prior edition, `superseded_at`), and the reindex **retires** superseded-version vectors. A nightly **reconciliation job** diffs Postgres ids vs vector payload ids, and treats any vector whose `kb_version ≠ live` as stale (repairs missing/stale/orphan). On student deletion, a cleanup job removes their `chat` vectors (retention, §5.9).
- **OLTP → OLAP:** CDC/refresh (event on quiz submit / mastery update; scheduled for coverage/readiness) runs **idempotent ETL** (upsert by natural key + as_of date) into facts. ETL is replay-safe; a watermark prevents double-counting.
- **Invariant:** business truth lives in OLTP; derived stores are rebuildable from OLTP at any time.

### 5.7 Caching & ephemeral (Redis)

| Keyspace | Purpose | TTL |
|---|---|---|
| `cache:answer:{hash}` | cached grounded answers; **`hash = f(normalized_query, board, class, subject, language, live kb_version)`** — prevents cross-cohort / wrong-language / stale-edition serving (NFR-1 <3s) | minutes–hours |
| `rl:user:{id}` / `rl:ip:{ip}` | token-bucket + sliding-window counters (SEC-3) | window |
| `sess:{id}` | short-lived session/stream state | short |
| `celery:*` | job broker/results | job |

### 5.8 State machines (status columns + guards)

| Entity | States | Guards |
|---|---|---|
| `quiz_attempt.state` | not_started→in_progress→(submitted\|auto_submitted)→graded | one attempt; within `[time_open,time_close]`; keys server-side; **a Celery-beat sweeper auto-submits+grades `in_progress` attempts past `time_close`** (fixes abandoned attempts, §3.9) |
| `guardian_link.status` | pending→(verified\|revoked) | 9–10 tutor access requires `verified` |
| `join_code` | active→(revoked\|expired) | joining creates `enrollment` (consent) |
| `enrollment` | joined→(left\|removed) | viewer read-only over student |
| `kb_document` | provenance: pending→(verified\|quarantined); lifecycle: ingesting→indexed→integrity_verified→live→superseded | ingest only if provenance `verified`; serve only `live`; one live edition per (board,subject) |
| `skill/mcp_server.status` + `vetting_verdict` | submitted→(admitted\|blocked); admitted→suspended | admit only with manifest + AgentSBOM |

### 5.9 Data lifecycle & governance

- **Minors' data:** minimal PII; chat content owner-only; `student_profile`/`message` classified sensitive; **never used to train models** (enforced by an export/data-use policy + access controls). **On erasure:** OLTP owned rows are hard-deleted and `chat` vectors purged; in OLAP the student is **pseudonymized** in `dim_student` (facts retained in anonymized/aggregate form so cohort & class reports stay stable rather than retroactively shifting) — policy captured in the deletion runbook (§11.3).
- **Provenance/lineage:** `kb_document` records source + integrity hash + version; the self-update pipeline only advances a version after a provenance pass.
- **Retention & backup:** security `audit_log` retained (tamper-evident, partitioned); `api_request_log` is daily-partitioned with a **configurable retention window** (drop old day-partitions), while the `fact_endpoint_calls` daily aggregate is kept longer for admin trend views; scheduled Postgres backups; derived stores rebuildable from OLTP.

### 5.10 Key query & reporting design

| Query | Reads from | Supporting structure |
|---|---|---|
| Weekly student report | `fact_coverage`, `fact_mastery_snapshot` | date-partitioned facts; MV `mv_weekly_student` |
| Class collective weak areas (subject-scoped) | `fact_quiz_attempt` ⋈ `dim_slo` | filter by teacher `subject_scope` + `space_id`; index on (space,subject,slo) |
| Exam-readiness + study-next | `fact_exam_readiness`, `mastery × frequency` | precomputed `fact_exam_readiness`; `slo_frequency_cluster` |
| Coverage % per subject | `fact_coverage` | latest snapshot per (student,subject) |
| Tutor grounded retrieve | vector DB + `curriculum_item` | HNSW + metadata filter; Postgres PK read |

Hot paths avoid N+1 (batched id reads); reports never recompute on the request path (served from MVs/facts).

---

## 6. Security Design — Secure Skills & MCP Layer

*(Defensive design occupying the supervisor template's "Security Considerations" slot.)* Baseline safety (guardrails, sandboxed visuals, rate-limit) ships in **P0**; the full vetting/manifest/SBOM layer is **P1**.

### 6.1 Vetting pipeline (admission)

```
submit(skill|mcp) → static scan (Semgrep) → capability claim-vs-actual
   (run in throwaway sandbox; observe syscalls/network/DB scopes vs declared)
   → mismatch/over-privilege? ── yes ──▶ BLOCK + vetting_result(blocked) + alert
   └─ no ─▶ assign least-privilege permission_manifest (OPA policy)
        → containerize (sandbox) → sign (sigstore/cosign) → admit
        → agent_sbom_entry(provenance, permissions, hash, signature)
```
A component runs **only** if `status=admitted` with a manifest + SBOM entry (FR-13/SEC-4/5/8).

### 6.2 Permission manifest (schema)

```json
{
  "component": "web_search@1.0.3",
  "granted_scopes": ["net:https://api.search.example"],
  "db_scopes": [],
  "fs": "none",
  "resource_limits": {"cpu":"0.5","mem":"256Mi","timeout_s":10},
  "network": {"default":"deny","allow":["api.search.example:443"]}
}
```
Least-privilege by default: `net:deny`, `fs:none`, no DB scope unless declared and justified. Enforced at runtime by **OPA/Rego** on each tool call.

### 6.3 Sandbox model

- MCP servers run in **containers** with read-only FS, seccomp, dropped caps, **network default-deny** (allowlist per manifest), and CPU/mem/timeout limits.
- **Visual rendering** (LLM05): the frontend renders typed specs in a **sandboxed iframe + strict CSP + DOMPurify**; the backend never returns executable HTML/JS.

### 6.4 Runtime guardrails

- **Input** (SEC-1/LLM01): Prompt Guard 2 / Llama Guard 3 on `guard_in`.
- **Output** (SEC-2/LLM05): Llama Guard 3 on `guard_out` + sandboxed visuals.
- **Tool-call policy**: every `ToolClient.call` is checked against the component's manifest (OPA); out-of-scope calls are denied + audited.
- **Content sanitization (indirect injection, LLM01):** retrieved context + tool/OCR/web outputs are quarantined/spotlighted (untrusted-data framing) before generation — complements `guard_in`/`guard_out` (§4.6).
- **Rate/anomaly** (SEC-3/LLM10): Redis token-bucket; anomalous behavior suspends the component (`status=suspended`).

### 6.5 AgentSBOM (format)

`agent_sbom_entry`: `{component, version, source, provenance, permissions[], content_hash, signature, admitted_at}` — the auditable inventory of every skill/MCP running, exportable for review (FR-13).

### 6.6 OWASP control mapping

| OWASP | Control | Where |
|---|---|---|
| LLM01 Prompt Injection | input guardrail + tool-call policy + `web_search` allowlist | 6.4, 4.5 |
| LLM04 Data/KB Poisoning | provenance/signature + integrity + version | 3.8, 5.9 |
| LLM05 Improper Output | sandboxed typed visuals (iframe/CSP/DOMPurify) | 3.7, 6.3 |
| LLM10 Unbounded Consumption | Redis token-bucket + quotas + concurrency caps | 3.9, 5.7 |
| Agentic/Skills Top 10 | vetting + least-privilege manifest + sandbox + AgentSBOM | 6.1–6.5 |
| Sensitive data (minors) | AES-256/TLS 1.3 + RBAC + minimal PII + audit | 6.7 |

### 6.7 Encryption, authz & audit

- **Encryption:** TLS 1.3 in transit; AES-256 at rest (disk + sensitive columns/secrets); secrets as encrypted CI/deploy secrets.
- **AuthZ:** RBAC (§3.1) enforced at API + data layer; subject-scoped teacher, read-only parent, owner-only student, class-gate.
- **Audit:** `audit_log` records who/what/when for tool calls and data access; minors-safe (no chat content in third-party views).

### 6.8 Row Level Security (SEC-13) — database-level authorization

RLS is a **second, independent enforcement layer** beneath application authorization. If an API handler forgets a `WHERE student_id = ...`, or a credential leaks, the database still refuses to return another student's rows.

**Context propagation.** Auth is application-managed, so Supabase's `auth.uid()` is unavailable. FastAPI instead sets the acting user per transaction:

```sql
SET LOCAL app.current_user_id = '<uuid from our JWT>';
```

`SET LOCAL` is transaction-scoped, which keeps it correct under connection pooling. Policies read it via `app.current_user_id()`; if unset the function returns `NULL` and **every policy denies** — fail-closed.

**Two non-obvious requirements** (getting either wrong makes all policies silently inert):

1. Table **owners bypass RLS by default**, so every table is set to `FORCE ROW LEVEL SECURITY`.
2. FastAPI connects as a dedicated **`app_backend` role with `NOBYPASSRLS`** — never as `postgres`. Background jobs that legitimately need unrestricted access (OLAP ETL, quiz sweeper, vector reconciliation) use the owner/service role instead.

**Policy model** (54 policies; helper functions in the `app` schema, `SECURITY DEFINER` to avoid recursion):

| Data | Rule |
|---|---|
| Own profile / progress / attempts | `student_id = app.current_user_id()` |
| Parent → child | `app.is_verified_guardian_of(student)` — requires `guardian_link.status='verified'` |
| Teacher → student | `app.teaches_student_subject(student, subject)` — active enrollment in the teacher's space **and** the subject in `teacher_subject_scope` |
| Chat (`chat_session`/`message`/`visual_aid`) | **Owner only.** No teacher, parent, or admin read path exists |
| `question_key` | **No policy at all** — the app role can never read answer keys (NFR-8 database backstop) |
| `audit_log`, `api_request_log` | Insert-only from the app, admin read; no UPDATE/DELETE policy, so the trail is tamper-evident |
| Curriculum taxonomy | Readable by any authenticated user; admin writes |

Enabling RLS on every `public` table also closes Supabase's PostgREST exposure of unprotected tables.

### 6.9 CI/CD hardening

GitHub Actions on every PR: unit/integration tests, **Semgrep** static analysis, **OPA policy tests**, the **Secure Skills & MCP scanner**, container build + **sigstore** signing. Protected `main`; only lead merges; secrets encrypted.

---

## 7. API Design

### 7.1 Conventions
- Base path `/api`; JSON; **JWT bearer** (access) + refresh rotation; `X-Request-Id` propagated to `audit_log`; SSE for tutor streaming; pagination via `limit/cursor`.
- RBAC via dependencies (`require_role`, `require_subject_scope`, `require_guardian_verified`, `require_owner`).

### 7.2 Endpoint catalog (consolidated)

Auth (§3.1), Tutor (§3.2), Quiz/Practice (§3.5), Spaces/Reports (§3.6), plus:

| Method | Path | Auth | Role | Purpose |
|--------|------|------|------|---------|
| GET | `/api/reports/weekly` | Yes | Student(own)/Parent(child) | Weekly coverage+performance (FR-4) |
| GET | `/api/reports/exam-readiness` | Yes | Student/Parent | Readiness + study-next (FR-16) |
| GET | `/api/admin/curriculum` | Yes | Admin | KB versions/provenance status |
| POST | `/api/admin/curriculum/ingest` | Yes | Admin | Trigger provenance-checked ingest (FR-12) |
| GET | `/api/admin/security/sbom` | Yes | Admin | AgentSBOM inventory (FR-13) |
| POST | `/api/admin/security/skills/{id}/vet` | Yes | Admin | Re-run vetting; admit/block |
| GET | `/api/admin/rate-limits` / PUT | Yes | Admin | View/configure quotas (FR-14) |
| GET | `/api/admin/logs/endpoints?date=YYYY-MM-DD` | Yes | Admin | **Per-day endpoint call logs** — method, endpoint, status code, message + daily counts/error-rate/p95 (admin panel); drill-down + aggregate |

### 7.3 Error model

Standard envelope: `{ "error": { "code": "...", "message": "...", "details": {...} } }`.

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | bad input |
| 401 | `UNAUTHENTICATED` | missing/expired token |
| 403 | `GATE_PENDING` | Class 9–10 parental link not verified |
| 403 | `FORBIDDEN_SCOPE` | role/subject/ownership violation |
| 409 | `ATTEMPT_EXISTS` | second quiz attempt blocked |
| 422 | `NOT_GROUNDED` | no confident curriculum answer (degrade) |
| 429 | `RATE_LIMITED` | over limit; `Retry-After` header |
| 503 | `MODEL_UNAVAILABLE` | fallback path engaged |

Rate-limited responses include `Retry-After` + `X-RateLimit-*` headers (SEC-3).

---

## 8. Development and Deployment

### 8.1 Prerequisites
Python ≥3.12, `uv`; Node ≥20 (Next.js); Docker + docker-compose; PostgreSQL ≥16; Redis ≥7; a GPU host for model serving (per §2.4); Git.

### 8.2 Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Supabase Postgres DSN. **Must use the `app_backend` role, not `postgres`** — connecting as the owner bypasses RLS (§6.8) |
| `SUPABASE_PROJECT_REF` | — | Project ref for `supabase link` / `db push` |
| `ANALYTICS_SCHEMA` | `analytics` | OLAP schema name |
| `VECTOR_DB_URL` | — | ChromaDB/FAISS endpoint |
| `REDIS_URL` | — | cache/rate-limit/broker |
| `JWT_SECRET` / `JWT_REFRESH_SECRET` | — | token signing (secret) |
| `LLM_ENDPOINT` / `LLM_FALLBACK_API` | — | self-host vLLM / hosted fallback |
| `EMBEDDING_ENDPOINT`, `RERANK_ENDPOINT`, `GUARDRAIL_ENDPOINT` | — | model services |
| `TTS_MCP`, `STT_MCP`, `OCR_MCP` | — | MCP server addresses |
| `RATE_LIMIT_DEFAULT` | e.g. `60/min` | per-user/IP quota (SEC-3) |
| `SIM_THRESHOLD` | **[PROPOSED]** | grounding similarity gate |

### 8.3 Project structure (monorepo)

```
edubridge-ai/
├── README.md · CLAUDE.md · docker-compose.yml · .github/workflows/ci.yml
├── prd.md · tdd.md
├── supabase/
│   ├── README.md                                          # setup + RLS connection pattern
│   └── migrations/*.sql                                   # AUTHORITATIVE schema (SQL-first)
├── backend/
│   ├── pyproject.toml · uv.lock
│   └── app/
│       ├── main.py                                        # FastAPI app factory
│       ├── core/           (config, security, deps, errors)
│       ├── auth/  agent/  skills/  mcp/  retrieval/        # modules:
│       ├── assessment/  classroom/  multimodal/            #  routes.py,
│       ├── pipeline/  reporting/  platform/  security/     #  service.py,
│       ├── analytics/      (OLAP models + ETL jobs)        #  models.py,
│       └── workers/        (celery app, tasks)             #  schemas.py
├── frontend/               (Next.js app router, components, i18n, sandboxed renderer)
├── mcp-servers/            (tts_avatar, stt, ocr, translation, web_search — separate procs)
├── ml/                     (model-serving configs: vLLM, whisper, bge, guardrails, fish-s2, musetalk)
└── infra/                  (Dockerfiles, compose, deploy)
```

### 8.4 CI/CD & serving
- **CI (GitHub Actions):** lint + unit/integration tests + Semgrep + OPA policy tests + Secure Skills/MCP scanner + Docker build + sigstore signing; PRs cannot merge unless green; `main` protected; only lead merges.
- **CD:** on merge/tag, deploy Dockerized frontend + backend + workers; apply schema with **`supabase db push`** (versioned SQL migrations); models served on cloud GPU instances (vLLM for Qwen + hosted fallback; Whisper/BGE/guardrails/Fish-S2/MuseTalk). Secrets as encrypted GitHub Actions secrets.
- **One-time manual step:** the `app_backend` role is created with `NOLOGIN` and no password (passwords are never committed). Set it out of band with `ALTER ROLE app_backend WITH LOGIN PASSWORD '…'` before pointing `DATABASE_URL` at it.

---

## 9. Testing and Verification

### 9.1 Strategy
- **Unit** (each skill/service/graph node in isolation — NFR-6), **integration** (module + DB + vector/Redis via testcontainers), **E2E** (Playwright for the tutor/quiz/classroom flows), **AI eval harness**, **security tests**.

### 9.2 E2E test cases (representative)

| Test | Steps | Expected |
|---|---|---|
| Student signup + gate | Class-9 signup, no parent | Tutor blocked (`GATE_PENDING`) until parent verifies |
| Grounded answer | Ask "math 9 chp4 ex4.5 q3" | Exact item + step-wise solution; cites slo ids |
| Generate-in-Urdu | Ask in Roman-Urdu | Urdu answer using glossary terms (not post-translated) |
| Class-adaptive language (FR-2) | Same concept, Class-9 vs FSc | FSc more technical; Class-9 simpler |
| Couplet tashreeh (FR-8) | Tashreeh of an in-corpus couplet | Template intro→meaning→tashreeh→devices→central idea; not fabricated |
| Essay/letter (FR-9) | Request essay/letter of a length | intro→body→conclusion; controlled length |
| Visual fallback | Ask for a diagram with no figure | Typed sandboxed render; no raw HTML in DOM |
| Adaptive quiz | Attempt with wrong answers | Difficulty adapts; one attempt; keys never in payload |
| Exam-readiness | After quizzes | Readiness score + study-next ranked by freq×(1−mastery) |
| Subject scope | Teacher opens other subject | `FORBIDDEN_SCOPE` |
| Rate limit | Exceed quota | `429` + `Retry-After` |
| Vetting | Submit over-privileged skill | Blocked; no AgentSBOM entry |
| Quran verbatim (FR-17) | Ask for a Quran translation verse | Returned word-for-word with reference; generation node skipped; missing verse → explicit "not found", never composed |
| Elective group | Class-11 pre-medical student opens subjects | Biology present, Mathematics absent; coverage computed only over group subjects |
| RLS isolation (SEC-13) | Student A queries with Student B's id | Zero rows — blocked by policy, not just app code |
| RLS answer keys | App role selects from `question_key` | Zero rows / denied — no policy grants access |
| RLS fail-closed | Query without `app.current_user_id` set | All queries denied |
| Self-update | Ingest unsigned source | Quarantined; not in KB |

### 9.3 AI eval harness
- **Retrieval groundedness** (answer cites retrieved curriculum) · **answer correctness** vs board answer keys · **BKT calibration** (predicted vs held-out outcomes) · **Urdu-TTS intelligibility** sample. Targets = PRD §22 KPIs.

### 9.4 Security tests
Guardrail-bypass attempts (LLM01/05), rate-limit 429 (LLM10), quiz-tamper (keys server-side), authz matrix (teacher cross-subject, parent write, 9–10 gate bypass, cross-student read), provenance quarantine (LLM04), OPA manifest enforcement.

---

## 10. Future Enhancements
- **P1 build-out:** full assessment/classroom/security layer (already designed here).
- **P2:** self-updating pipeline breadth; broaden the full PCTB+STBB × 9–12 × all-subjects matrix; admin depth.
- **Stretch:** diffusion image generation; guardrail-moderated student↔teacher chat; advanced analytics; additional boards.

---

## 11. Maintenance and Support

### 11.1 Version history
| Version | Date | Changes |
|---|---|---|
| 0.1.0 | 2026-07-19 | Initial TDD from accepted PRD. |

### 11.2 Known limitations
Curriculum coverage gated by data digitization (proposal §1.7); Urdu is not top-tier for TTS (fallback designed); LLM reasoning bounded (controlled skills only); self-hosting needs GPU budget (§2.4).

### 11.3 Runbooks
KB refresh (provenance→version→reindex→reconcile), model update/rollback, incident (guardrail/vetting alerts), OLAP rebuild from OLTP, backup/restore.

---

## 12. References
Proposal `EDUBRIDGE_AI_PROPOSAL.pdf`; `prd.md`; OWASP LLM Top 10 (2025) & Agentic/Skills Top 10 (2026); MCP spec; LangGraph; FastAPI; PostgreSQL; ChromaDB/FAISS; BGE-M3; Qwen; Whisper; Fish Audio S2 Pro; MuseTalk.

---

## 13. Technical Requirements (consolidated)

- **Stack:** §2.2. **Architecture tree:** §8.3. **DB schema:** authoritative SQL in `supabase/migrations/` (approach in §5.4, vector §5.5, OLAP §5.6). **API:** §7. **Deployment:** §2.4 + §8.4.
- **Data stores:** **Supabase managed PostgreSQL** (OLTP source of truth, RLS enforced) + dedicated vector DB (ChromaDB/FAISS) + `analytics` star schema + Redis.
- **Curriculum:** 2 boards × 4 classes × 10 subjects with per-class lists and elective groups → **76 subject definitions**; four content strategies incl. religious-verbatim.
- **Models (self-host primary):** Qwen (vLLM) + fallback, Whisper, BGE-M3/reranker, Qwen2.5-VL, Prompt Guard 2/Llama Guard 3, Fish S2 Pro, MuseTalk.
- **Deployment requirements:** GPU host (§2.4 option, [PROPOSED]); Docker; encrypted secrets; TLS 1.3; backups.

---

## 14. Validation & Critical Review

This TDD was subjected to an **adversarial critical review** (an independent reviewer agent red-teaming the design against the PRD) plus a self-review across the seven solidity gates. **15 findings** were raised; all were accepted and resolved in this draft (v0.1.0). Summary:

| # | Sev | Finding | Resolution | Where |
|---|-----|---------|------------|-------|
| 1 | High | Curriculum taxonomy unversioned under versioned KB; `slo` RESTRICT blocks retirement; `kb_document` board-wide | SLOs SCD soft-retire (`effective_from_year`, `retired_at`, never delete); `kb_document` scoped to `subject_id` | §5.4, §5.1 |
| 2 | High | No active/live KB-version pointer; edition mixing; dropped ingest states | `kb_document.is_live` + `kb_lifecycle` (…→live→superseded); retrieval pins live version; reconciliation retires stale vectors | §5.4/5.5/5.6a/5.8 |
| 3 | High | Parental-consent gate forgeable (self-register as parent) | `CHECK(parent_id≠student_id)`; service enforces parent role + **out-of-band** verification (`verification_method`) | §5.4, §3.1 |
| 4 | Med | Two parent↔child link mechanisms (guardian_link vs enrollment) | Canonical `guardian_link`; guardian-space path creates/verifies it | §3.1, §3.6 |
| 5 | Med | Answer keys co-located with served `question` (NFR-8 risk) | Split into server-only `question_key` table; never in any client schema/route | §5.3(c) |
| 6 | Med | Auto-submit had no server job | Celery-beat **sweeper** grades `in_progress` past `time_close` | §3.9, §5.8 |
| 7 | Med | `teacher.subject_scope` under-modeled | Explicit M:N `teacher_subject_scope`; report predicate joins through it | §5.3(a), §3.6 |
| 8 | Med | 9–10 gate only on "tutor endpoints" | Gate applied to **all** student learning/assessment routes + per-route test | §3.1, §9.4 |
| 9 | Med | Per-question fact grain skews SLO weak-area attribution (M:N) | `primary_slo_id` + `fact_attempt_slo` (student×SLO) + fractional allocation rule | §5.6 |
| 10 | Med | Cache key composition unspecified (cross-cohort/lang leak) | Key = f(query, board, class, subject, language, live kb_version) | §5.7 |
| 11 | Med | `chat` vectors in derived store lack per-owner read filter | Mandatory `student_id` filter on chat-collection reads | §5.5, §5.9 |
| 12 | Med | Per-IP rate limit self-DoSes institutions behind NAT | Institution-aware per-IP ceilings; per-user inside sessions | §3.9 |
| 13 | Low-Med | Minors' erasure vs OLAP facts unreconciled | Pseudonymize `dim_student`, retain anonymized facts; runbook | §5.9, §11.3 |
| 14 | Low-Med | Guardrails missed retrieved/tool content (indirect injection) | Spotlight/sanitize retrieved + tool outputs before generation | §4.6, §6.4 |
| 15 | Low | E2E gaps (FR-2/8/9); unbounded `guard_out` loop | Added E2E rows; `guard_out` block → refuse/degrade, max-1 retry | §9.2, §4.2 |

**Gate outcome after fixes:** data-model integrity, three-store consistency, security, flow soundness, and internal consistency now pass; PRD traceability was clean throughout (all FR-1…16, SEC-1…12, NFR-1…8 map to component + API + test).

### 14.1 Changes in v0.2.0 (post-review)

| Change | Driver | Where |
|---|---|---|
| OLTP moved to **Supabase**; Supabase CLI migrations replace Alembic | Platform decision | §2.2, AD-6/AD-7, §8 |
| **Row Level Security** designed and implemented (54 policies, `app_backend` role, session-variable context) | Defense-in-depth for minors' data | §6.8, SEC-13 |
| Subjects **6 → 10**, per-class lists, **elective groups** (`student_group`) | Real board structure | §5.3a/b, PRD §2.4.1 |
| Two branches → **four `content_strategy` values** | English and religious content need distinct handling | §3.4, §4.6, PRD §2.4.2 |
| **Religious-verbatim mode** — generation node disabled for Quran Translation | FR-17; ethical + accuracy requirement | §4.6, §9.2 |
| `subject_group`, `class_level`, `agent_component`, `question_key` | Normalization; polymorphic FK removal; NFR-8 backstop | §5.2, §5.3 |
| `uuidv7()` → `gen_random_uuid()`; `audit_log` composite PK | **Both would have failed on PostgreSQL ≤17** | §5.4 |
| Inline DDL replaced by a pointer to `supabase/migrations/` | Prevent schema drift between doc and code | §5.4 |

**Still open (decisions, not defects):** deployment target §2.4, vector DB choice §5.5, GPU spec, similarity threshold `SIM_THRESHOLD`, and the Class-11 ICS subject list (PRD §2.5).

**Not yet verified:** the migrations have **not been executed against a live database**. First `supabase db push` should be treated as the real test.

---

**Document Status:** Draft v0.1.1 — critically reviewed, awaiting user section-by-section review.
**Next Review:** on resolution of the [PROPOSED] items and user feedback.
**Downstream:** on acceptance, this TDD drives Epics → Stories → Tasks → Implementation.








