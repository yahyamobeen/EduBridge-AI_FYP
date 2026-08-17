# Technical Design Document
## EduBridge AI — A Secure, Agentic, Multilingual Learning Platform (Classes 9–12, PCTB & STBB)

**Version:** 0.3.7
**Status:** Draft — under section-by-section review
**Last Updated:** August 9, 2026
**Purpose:** Implementation-ready technical design derived from `prd.md`, for a curriculum-grounded, agentic, multimodal, multilingual tutoring + classroom-analytics platform with a Secure Skills & MCP Layer.
**Product Owner:** EduBridge AI Team (Group Leader: Yahya Mobeen) · **Supervisor:** Dr. Muhammad Arif Butt (FCIT, University of the Punjab)
**Source of truth:** `prd.md` (this TDD implements it) · **Upstream:** `EDUBRIDGE_AI_PROPOSAL.pdf`

> **Design approach:** *data-first / DB-led.* The data model (§5) is the backbone; component boundaries (§3), APIs (§7), and analytics are derived from it. Every design decision traces to a PRD requirement (`FR-`, `SEC-`, `NFR-`). Items marked **[PROPOSED — confirm]** are open decisions for review.

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.3.9 | 2026-08-17 | EduBridge AI Team | **Transactional email provider resolved to SendGrid, and the guardian invite is actually delivered (KAN-21).** The `EmailSender` seam in `app/auth/email.py` gains **`SendGridEmailSender`**; the factory returns it when `EMAIL_PROVIDER=sendgrid`, and `email_provider`'s `Literal` gains the value — **both halves are required**, because a sender class whose name is absent from the Literal is refused at boot rather than ignored (that is v0.3.8's A3 fix behaving correctly). `Settings` gains `SENDGRID_API_KEY`, and the `EMAIL_FROM` guard now covers **every** real provider rather than naming one. The `email` extra adds `sendgrid>=6.11.0`; `requirements.txt` is regenerated, since Render installs from it. `EMAIL_PROVIDER=logging` remains the safe default and stays refused in production. Resend is retained but unused: its unverified free tier delivers **only to the account owner's own address**, which is what made it unusable for a guardian invite. **A10 closes** — `guardian_invite()` builds the confirm URL, renders the email and queues it to the parent through the after-commit outbox (v0.3.8's D1 seam), so an invite is released only if the transaction that minted its token commits. **C3 closes in the same change**, because wiring A10 is what made it reachable: `student_name` is `app_user.full_name`, editable at will through `PATCH /auth/me`, so escaping is now structural — `_wrap` escapes the document title, the body escapes text content with `quote=False` so a real *O'Brien* is not mangled, and the subject **header** is flattened rather than entity-escaped, a CR/LF being the injection a header actually suffers. The invite's language is read from `app_user.language_pref`, not the `student_profile` copy v0.3.8 superseded (§3.1, §8.2). |
| 0.3.8 | 2026-08-17 | EduBridge AI Team | **Epic 1 correctness pass (Phases 3–7).** §3.1 gains the three **account-management routes** the document had specified and the code never had — `PATCH /api/auth/me`, `POST /api/auth/password/change` and `GET /api/auth/2fa/status`, the last carrying **`backup_codes_remaining`**. `language_pref` moves from `student_profile` to `app_user`, because FR-A8 is "Role: all" and the lookup behind every outgoing email joined a table teachers, parents and administrators have no row in — so **no non-student could ever receive Urdu mail**. §7.3 records that `password/change` answers `401 UNAUTHENTICATED` for a wrong current password rather than inventing a code. **Sessions gain an end**: an absolute ceiling on a rotating refresh chain, atomic rotation under a row lock (closing the two-tab race that forked a token family), and account-wide invalidation on password change — the last of which widens its cutoff by a configurable **clock-skew allowance**, measured at 1.1s between the application and database hosts and in the direction that made the check silently inert. Refusals now follow the onboarding order, every credential-bearing field is length-bounded, and outgoing email is dispatched **only after the transaction commits** (D1), so a request that fails late no longer mails a link for a token that was rolled back. `email_provider` and `environment` become `Literal`s (**A3**), turning a typo into a boot failure instead of a silent fall-through to the logging sender. |
| 0.1.0 | 2026-07-19 | EduBridge AI Team | Initial TDD draft derived from the accepted `prd.md`; matches supervisor TDD format, extended to engineering depth. Data-first (polyglot store + star-schema OLAP). |
| 0.1.1 | 2026-07-19 | EduBridge AI Team | Applied 15 critical-review fixes (§14); locked **Celery**; GPU/model-serving **mostly cloud**; added `api_request_log` + `fact_endpoint_calls` + admin **daily endpoint-logs** panel. |
| 0.3.7 | 2026-08-09 | EduBridge AI Team | **Consistency pass, driven by writing the User Stories & Epics deliverable.** §3.1 gains the **account-management routes** — `PATCH /api/auth/me`, `POST /api/auth/password/change`, `GET /api/auth/2fa/status` — closing a gap where `prd.md` §4.2 granted every role "manage own account" and this document routed nothing for it (now `prd.md` FR-A8). §3.6's claim that "the guardian-space join path creates/verifies a `guardian_link`" is **corrected**: the v0.3.5 write boundary in §6.8 already made `verified` reachable only through `app.confirm_guardian_link` with a one-time invite token, so a join code could never have verified anything — the student-initiated invite is the sole route, and parents create no spaces. §5.4's migration table listed **4 of the 11 applied migrations**, omitting `20260803090000_guardian_link_write_boundary.sql` — which §6.8 cites by name — and six others; all eleven are now documented with what each does. §5.4 also records that the subscriptions migration took the schema from **45 to 48 tables**. §7.3's error table was **split in half by two prose paragraphs**, so `NOT_GROUNDED`, `RATE_LIMITED` and `MODEL_UNAVAILABLE` rendered as a header-less fragment; the table is whole and the prose follows it. §11.1's second one-row version table, which claimed v0.1.0, is removed, and the closing Document Status no longer reads "Draft v0.1.1". No design decision changed in this pass — every edit brings the document into line with what was already decided or already applied. |
| 0.3.6 | 2026-08-03 | EduBridge AI Team | **2FA / email / password-reset hardened (KAN-10b review fixes).** §6.9 D7 now applies to **enrolment as well as challenge**: `/2fa/confirm` counted no failures and never locked, so a six-digit emailed OTP was guessable with only a per-address limiter in the way — and `upsert_2fa_enrollment` cleared `failed_attempts`/`locked_until`, so the client's enrolment resend (a re-call of `/2fa/enroll`, §14.4 finding 2) laundered any lockout that did exist. Enrolment also records the TOTP step it consumed, closing a window in which the code that completed enrolment was replayable at `/2fa/verify`. Rate limits gain a **per-account** layer, because an address-keyed limit of ten verifications per five minutes is ten for an entire school lab. Transactional mail is **locale-aware** (§3.1): every link carried `/en/` in an Urdu-first product; copy stays English pending a human writer, but the URL locale is correct now. Mail leaves the request thread so `password/forgot` is constant-time in fact and not only in intent — a synchronous provider call in the known-address branch was an enumeration oracle the dummy hash did not cover. §7.3 gains the `INVALID_TOKEN`/`TOKEN_EXPIRED` rule for **spent** tokens. At this revision **no provider was chosen** — the Resend SDK was an optional extra and `EMAIL_PROVIDER=logging` was refused in production; that decision was later resolved to **SendGrid** in v0.3.9. |
| 0.3.5 | 2026-08-03 | EduBridge AI Team | **Guardian gate hardened (RBAC-002 review fixes).** §6.8 gains the `guardian_link` **write boundary**: either participant may INSERT only as `pending`, only the parent may UPDATE and never to `verified`, so the status is reachable through `app.confirm_guardian_link` alone — the policies now enforce the anti-forgery claim §3.1 had been making on their behalf. The student's re-invite reset moves to `app.reinvite_guardian_link`, because the applied `guardian_link_update` is parent-only and the student's UPDATE was matching zero rows **silently**: a resend after a revoke reported success while changing nothing and produced an unconfirmable invitation. §3.1 rule 3 extends to an **unknown class level**, which now fails closed rather than waving the student through. New error code **`GUARDIAN_NOT_FOUND` (422)** catalogued in §7.3 — it was already being returned. Rate limits on the authenticated guardian endpoints key on the **acting user** rather than the address, so a shared school-lab or carrier-NAT address no longer makes one student spend the cohort's allowance. `guardian/confirm` returns `student_name` as **nullable**, matching `app_user.full_name`. |
| 0.3.4 | 2026-08-02 | EduBridge AI Team | **Frontend feature-complete (Phases 10–12).** Plan selection, the role guard, the three dashboard shells and the error boundary. §6.11 records a **deviation**: `script-src` now carries `'unsafe-inline'`, because the Phase-1 policy blocked the App Router's inline bootstrap scripts and left the whole application non-interactive in production (**new §14.5**). §9.5 gains two enforced rules — the RTL physical-property sweep and the parent-navigation assertion — plus the requirement that a production build be opened and interacted with before a phase is done. |
| 0.3.3 | 2026-08-02 | EduBridge AI Team | **Frontend auth screens built (Phases 6–9).** §3.10 gains the rules the implementation forced: challenge credentials (`pending_token`, `enrollment_token`) stored in memory under the access token's rule; the `200`-always-advances login discriminator and its `noRetry` consequence; the 2FA challenge opening on the server's method with a server-driven lockout; `type="text"` for one-time codes; per-minute countdown announcements; site chrome scoped by route group. New **§14.4** records the contract findings for the backend tracks — chiefly that **nothing switches the second factor mid-challenge** (`2fa/resend` only re-sends to a user already enrolled in email OTP), that **enrolment has no resend at all**, and that guardian status has **no push channel**. Prototype links to unbuilt areas now resolve to a coming-soon page rather than being removed. |
| 0.3.2 | 2026-08-02 | EduBridge AI Team | **Subscriptions + onboarding state.** New `subscription`, `subscription_plan`, `oauth_identity` tables (§5.3a, §5.4) with RLS (§6.8); `onboarding_state` documented as a **derived** field gaining `plan_selection_pending` (§3.1) — the first **non-monotonic** state in the system (§5.8). `guardian/confirm` becomes **authenticated** (§3.1) — the parent signs up first. `email/verify` and `2fa/confirm` now issue tokens, and the 2FA enrolment endpoints take `enrollment_token` in the **body** (§3.1, §7.3). Frontend design specified in depth (§3.10): API client, in-memory access token, `NAV_BY_ROLE`, RTL rule, `qr_svg` handling (§6.11). Teacher tutor access removed to match `/api/tutor/ask` scoping (§3.2, `prd.md` §4.2). Frontend test matrix added (§9.5). |
| 0.3.1 | 2026-08-01 | EduBridge AI Team | Login returns **`200` + `status` discriminator** rather than `401 TWO_FACTOR_REQUIRED` (§3.1, §6.9, §7.3, §9.2); the two affected codes removed from the error catalogue. |
| 0.3.0 | 2026-08-01 | EduBridge AI Team | **Two-factor authentication for all roles** (SEC-14 / FR-A4): TOTP primary, email-OTP alternative, hashed single-use backup codes, admin-assisted recovery. Adds `two_factor_enrollment` and `two_factor_backup_code` tables plus two `token_kind` values; login becomes a two-step challenge (§3.1, §6.9). |
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
| **Frontend** | Next.js (App Router) + React + Tailwind **v3**; next-intl | Next 16, React 19, TS 6 | Responsive web UI, i18n/RTL |
| **Frontend data / forms** | TanStack Query; react-hook-form + zod | latest | Cached identity checks on metered connections; multi-step signup with cross-field rules |
| **Frontend testing** | Vitest + React Testing Library + jsdom | latest | Unit and component only — E2E is the backend track's (§9.5) |

**Two version notes recorded while scaffolding**, both of which change how the project is driven:

- **`next lint` no longer exists.** Next 16 removed the subcommand, so linting runs ESLint directly
  (`eslint .`) against a flat `eslint.config.mjs`. `eslint-config-next` 16 exports flat-config arrays, so no
  `FlatCompat` shim is needed.
- **Tailwind is pinned to v3, not v4.** The `DESIGN.md` tokens are a JS object that maps straight onto v3's
  `theme.extend`, and all 15 mockups are v3-shaped. v4's CSS-first `@theme` would mean re-deriving the token
  set by hand for no gain at this stage.
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
| GET | `/api/reference/enums` | No | — | Boards, class levels, **groups keyed by class**, mediums, languages. Signup reads its options from here rather than hard-coding them |
| POST | `/api/auth/register` | No | — | Create student (board/class/**group**/medium/language); teacher/parent variants. **`role` accepts `student`, `teacher`, `parent` only — never `admin`** (FR-A2a); an `admin` value is `400 VALIDATION_ERROR`. **Issues no session** — the account starts at `email_verification_pending` |
| POST | `/api/auth/login` | No | — | Authenticate → `200` + `status` discriminator (never a session directly). **Refuses administrators** (FR-A2a) with a `401 UNAUTHENTICATED` whose body is identical to a wrong password — not a `403`, which would let anyone enumerate administrator addresses by status code |
| POST | `/api/auth/admin/login` | No | — | The administrator half of the same rule. Same request and same response union as `/auth/login`; refuses every **non**-administrator with the identical `401`. Its own rate-limit bucket, so hammering the public form cannot lock administrators out. Reached through an unlisted path (`ADMIN_LOGIN_PATH`, a server-only variable), which is **not** the control — this role check is. The 2FA, refresh and logout continuations are deliberately **shared** with `/auth/login` |
| POST | `/api/auth/email/verify` | No (token) | any | Verify address → **returns `access_token` + `enrollment_token`** (v0.3.2) |
| POST | `/api/auth/email/resend` | No | any | Re-send the verification email (rate-limited) |
| POST | `/api/auth/password/forgot` | No | any | Begin reset. Response is identical whether or not the address exists |
| POST | `/api/auth/password/reset` | No (token) | any | Complete reset with a new password |
| POST | `/api/auth/2fa/enroll` | **`enrollment_token` in body** | any | Start enrolment — returns TOTP `qr_svg` + secret, or triggers email-OTP |
| POST | `/api/auth/2fa/confirm` | **`enrollment_token` in body** | any | Confirm first code; activates 2FA, returns the 10 backup codes **once** and an **`access_token`** (v0.3.2) |
| POST | `/api/auth/2fa/verify` | Pending-2FA token | any | Submit TOTP / email-OTP / backup code → full session |
| POST | `/api/auth/2fa/resend` | Pending-2FA token | any | Re-send an email-OTP (rate-limited) |
| POST | `/api/auth/2fa/backup-codes` | Yes | any | Regenerate backup codes (invalidates the old set) |
| POST | `/api/admin/users/{id}/2fa/reset` | Yes | Admin | Identity-verified recovery reset; always audited |
| POST | `/api/auth/refresh` | Refresh JWT | any | Rotate access token |
| POST | `/api/auth/logout` | Yes | any | Revoke refresh token |
| POST | `/api/auth/guardian/invite` | Yes | Student | Invite a parent **by email address** to satisfy the 9–10 gate |
| POST | `/api/auth/guardian/confirm` | **Yes (parent)** | Parent | Parent confirms link → `guardian_link.status=verified` (v0.3.2 — see below) |
| GET | `/api/auth/guardian/status` | Yes | Student | Poll link state while the gate is pending |
| GET | `/api/auth/me` | Yes | any | Current identity + **`onboarding_state`** |
| PATCH | `/api/auth/me` | Yes | any | Update own profile and **stored `language_pref`**, which governs outgoing email (v0.3.7 — FR-A8) |
| POST | `/api/auth/password/change` | Yes | any | Change password from inside the account; **requires the current password** (v0.3.7 — FR-A8) |
| GET | `/api/auth/2fa/status` | Yes | any | Own second-factor method and state, plus **`backup_codes_remaining`**. **Never returns the secret** (v0.3.7 — FR-A8; count added v0.3.8) |

**Key design decisions:**
- Passwords hashed with **argon2id** (never MD5 — the supervisor's template's MD5 is the explicit anti-pattern we avoid). Refresh tokens stored hashed, rotated, revocable.
- RBAC via FastAPI dependencies: `require_role(...)`, `require_subject_scope()`, `require_guardian_verified()`. The gate dependency blocks **every student learning/assessment endpoint** for a Class 9–10 student whose `guardian_link` is not `verified` — `/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, and `/api/reports/*` (returns `403 GATE_PENDING`). An authz-matrix test asserts the gate on each such route (§9.4).
- **Anti-forgery of the gate (mechanism fixed in v0.3.2, enforced in the database in v0.3.5):** the link is created by a **student-initiated email invite** — the student supplies a parent's address, the parent **signs up**, and confirms the link from their own authenticated account. `guardian_link` has `CHECK(parent_id≠student_id)` and the service enforces `parent_id.role='parent'`. The RLS write boundary in §6.8 is what makes this more than a convention: neither participant can write `verified` at all, so the token path is the only way in.
- **The gate FAILS CLOSED on an unknown class level.** A student with no readable `student_profile` row is gated, because under RLS an unreadable row is indistinguishable from an absent one and the failure mode of guessing wrong is serving a 14-year-old as though they were 18. `guardian_required` and the gate agree on this deliberately — if the gate holds, `onboarding_state` must report `guardian_link_pending` so the student lands on a screen that can resolve it.
  - `guardian/confirm` is therefore **authenticated**, not token-only as it was through v0.3.1. Requiring a real parent account before the link verifies is what makes the signal out of band: confirmation happens in a mailbox *and* an account the student does not control.
  - A **redeemable code** was considered and rejected. Any code the student types has, by definition, passed through the student — so it is not out-of-band, and a student could register a throwaway "parent", generate a code and clear their own gate. That is precisely the forgery this control exists to stop (§14 finding 3).
- **Single canonical parent↔child link:** `guardian_link` is the only source of truth for "a parent may view a child" and for the gate; the guardian-space path (§3.6) creates/verifies a `guardian_link`, it does not rely on `enrollment`.
- **Enforcement is at the API + data layer**, not the UI, so it cannot be bypassed by calling the API directly (security gate #4).
- **RLS context is set per transaction.** Because auth is application-managed, every request transaction issues `SET LOCAL app.current_user_id = '<uuid>'` before any query, which the RLS policies read (§6.8). If it is not set, policies deny everything — fail-closed.
- **Student registration captures `student_group`** alongside board/class/medium; a database `CHECK` rejects invalid class/group pairs (e.g. a Class-9 student marked `pre_medical`).
- **Two-step login (SEC-14).** A correct password does **not** produce a session. `POST /api/auth/login` returns **`200` with a `status` discriminator** — the request succeeded, it is simply incomplete — carrying a short-lived, single-purpose **pending-2FA token** (≈5 min, cannot call any business endpoint). Only a successful `/2fa/verify` exchanges it for access + refresh JWTs. A **wrong** password is a genuine failure and returns `401 UNAUTHENTICATED`. Full design in §6.9.

- **`onboarding_state` is derived, never stored.** `GET /api/auth/me` computes it per request; there is no column and no enum, so adding a state needs no migration. Precedence is fixed and evaluated in order:

  | Order | Condition | State |
  |---|---|---|
  | 1 | `app_user.email_verified_at IS NULL` | `email_verification_pending` |
  | 2 | `two_factor_enrollment.status <> 'active'` | `two_factor_enrollment_pending` |
  | 3 | student, class 9–10 **or class level unknown**, `guardian_link.status <> 'verified'` | `guardian_link_pending` |
  | 4 | student, `subscription.status NOT IN ('trialing','active')` **or no record** | `plan_selection_pending` |
  | 5 | otherwise | `active` |

  Clients route on this single field. They must not reconstruct it from the underlying booleans — that is how the four tracks drift apart.

- **Onboarding is not monotonic (v0.3.2).** Rule 4 can fire *after* a user has been `active`: a student's trial lapses and they return to `plan_selection_pending`. Any consumer that evaluates the state once at session start and then caches `active` will strand that user on a page they no longer have rights to. The state must be re-evaluated on every identity check. This is the only backward transition in the system (§5.8).

- **Rule 4 fails closed.** *No* subscription row means no access — never "still trialing". A failed insert at registration must not silently grant indefinite free access (`prd.md` MON-2).

- **The token issued by `email/verify` is scoped (v0.3.2).** Returning a session before the second factor exists would make email verification alone a complete login and render 2FA bypassable. That token must be accepted **only** by the onboarding endpoints and must be rejected by every business route. It is a narrower credential that happens to share the access-token shape, not a general session.

- **`enrollment_token` travels in the request body**, matching how `/2fa/verify` already carries `pending_token`, rather than in an `Authorization` header. One convention for short-lived, single-purpose tokens; the header is reserved for real sessions.

**Interfaces:** `AuthService.register()`, `.login()`, `.rotate_refresh()`, `.onboarding_state(user)`, `GuardianService.invite()/confirm()/is_verified(student_id)`.

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
- **Single parent-link source of truth:** `guardian_link` alone carries parent visibility and the 9–10 gate; neither ever depends on `enrollment` (avoids the dual-mechanism gap). **There is no space-based linking path (corrected in v0.3.7).** Through v0.3.6 this read *"the guardian-space join path creates/verifies a `guardian_link`"*, which the v0.3.5 write boundary in §6.8 had already made impossible: `verified` is reachable only through `app.confirm_guardian_link`, which demands an unexpired one-time `guardian_invite` token, and a join code produces none. Parents therefore create no spaces and issue no join codes (`prd.md` §4.2, v0.3.5).
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

**Responsibilities:** auth & onboarding screens, role dashboards, tutor chat (text+voice, streaming), sandboxed visual renderer, avatar/audio player, classroom/quiz UIs, i18n (EN/UR/Roman-Urdu) with **RTL**.

**Stack:** Next.js (App Router) · TypeScript `strict` + `noUncheckedIndexedAccess` · Tailwind · `next-intl` ·
TanStack Query (data) · react-hook-form + zod (forms) · Vitest + React Testing Library (unit/component) ·
**Playwright** (E2E, consistent with §9.1).

**Key design decisions:**

- **Sandboxed visual renderer** component: renders the typed visual spec inside an `<iframe sandbox>` with a strict CSP; any string is passed through **DOMPurify**. This is the frontend half of LLM05.

- **Token handling.** The **access token lives in memory only** — never `localStorage`, `sessionStorage`, a
  readable cookie, or a URL. The **refresh token is an httpOnly cookie** the server sets and JavaScript never
  reads. *(Corrects v0.3.1, which said "auth tokens in httpOnly cookies" — that would have put the access
  token somewhere the client must read it from, which is not achievable with httpOnly.)*
  - Refresh is **single-flight**: N concurrent 401s trigger one refresh, not N.
  - Refresh fires **proactively at ~80 % of `expires_in`**, so a student mid-form is not interrupted.
  - The 401→refresh→retry path is **allow-listed by error code**. `TWO_FACTOR_INVALID` and
    `PENDING_TOKEN_EXPIRED` are also `401`s but mean "wrong code" — retrying them would resubmit a bad code
    and consume a lockout attempt.

- **Routing is driven by `onboarding_state` alone** (§3.1), re-evaluated on every identity check because the
  state is non-monotonic. The client never infers progress from `class_level` or a set of booleans — which is
  also why a Class 11–12 student has no code path that can render the parental gate.

- **Navigation is derived per role from the `prd.md` §4.2 matrix**, through a single `NAV_BY_ROLE` map. A role
  never renders a control it lacks the right to use, even disabled.

  | Student | Teacher | Parent |
  |---|---|---|
  | Dashboard · Subjects · AI Tutor · Practice · Quizzes · Progress · **My Classes** · Study Planner | Dashboard · My Spaces · Quizzes · Reports *(subject-scoped)* · Class Roster · SLO Mapping · Announcements | Dashboard · My Child · Progress · How to Help |

  Three points this encodes, each of which a shared component tree makes easy to get wrong:
  **(a)** the parent surface is strictly read-only and exposes **no** tutor, chat-replay or planner-write
  control — `GET /api/tutor/sessions/{id}` is student-owner-only, so a "replay this session" affordance
  would advertise a capability RLS and the matrix both deny;
  **(b)** the teacher surface has **no** tutor entry, matching `/api/tutor/ask` (§3.2);
  **(c)** the student surface must expose **My Classes**, because `prd.md` §4.2 guarantees a student can see
  who can view them and leave any space at any time — a right with no UI is not a right.

- **i18n and RTL.** `next-intl` with a `[locale]` route segment, all locales prerendered. **`ur` is the only
  RTL locale; Roman-Urdu is Latin script and stays LTR.** Mirroring uses **logical** spacing and alignment
  properties throughout, so a new screen is correct by construction rather than by remembering; directional
  icons flip, non-directional ones do not; one-time codes, backup codes and countdown numerals are pinned
  LTR inside RTL pages (`prd.md` I18N-4).

- **Web locale ≠ stored language value (`prd.md` I18N-5).** Routing uses `en` · `ur` · **`ur-Latn`**, while
  the API and `language_code` enum use `en` · `ur` · **`roman_ur`**. `roman_ur` is not a valid BCP-47 tag —
  `Intl` throws `RangeError` on it and `<html lang="roman_ur">` is meaningless to a screen reader — so it
  cannot be used as a web locale. Conversion lives in one module and is covered both directions by tests.
  **No backend change is implied:** the API keeps returning `roman_ur` in `languages` and accepting it for
  `language_pref`.

- **The Urdu face is loaded only for `ur`.** It is registered with preloading disabled and its CSS variable
  applied conditionally, so an English or Roman-Urdu visitor never downloads a Naskh font they cannot read —
  a meaningful saving on the metered connections in `prd.md` A11Y-2.

- **Language switching is a set of real links, not a client-side control.** Each locale is a genuine URL, so
  switching works without JavaScript and costs one tap; the current path is preserved, so a user switching
  language mid-journey is not thrown back to the home page.

- **Locale detection is disabled; English is the default (`prd.md` I18N-1a).** Left at the library default,
  the locale is negotiated from `Accept-Language` and a `NEXT_LOCALE` cookie, so a browser set to Urdu is
  redirected to `/ur` before the visitor chooses anything. Verified by request: with detection on, a request
  carrying `Accept-Language: ur` was sent to `/ur`; with it off, every variant resolves to `/en` and explicit
  `/ur` still serves normally. The trade-off accepted is that the cookie is disabled too, so a returning
  visitor lands on `/` in English; they remain in their chosen language while navigating, because every link
  carries the locale prefix. Honouring the cookie while still ignoring `Accept-Language` would require
  custom middleware — next-intl exposes one flag for both.

- **Short-lived challenge credentials follow the access token's storage rule.** `pending_token` and
  `enrollment_token` complete an authentication step, so presenting one *is* authenticating. They live in a
  module variable and nowhere else — never web storage, a readable cookie, or a query string. The
  consequence is deliberate: a reload on `/login/2fa` loses the challenge and the screen returns the user to
  sign-in. A token that survived a reload would also survive the user walking away from the shared device
  `prd.md` §3.1 describes.

- **A `200` from `/auth/login` is never a failure.** It means the password was right and the journey is
  unfinished, so the client branches on `status` and moves forward: `two_factor_required` → the challenge,
  `two_factor_enrollment_required` → enrolment, `email_verification_required` → the check-your-email screen.
  **Only a `401` is a credential error**, and it renders one neutral message for both "no such account" and
  "wrong password", so the form cannot be used to enumerate registered addresses (§6.3). Two consequences
  that are easy to miss: the `email_verification_required` payload carries a **masked** address, which
  `/auth/email/resend` cannot act on, so the client keeps the unmasked address the user typed; and a `401`
  here must **not** trigger refresh-and-retry, so the client exposes a per-request `noRetry` flag rather than
  firing a guaranteed-to-fail refresh on every typo.

- **The 2FA challenge opens on the method the server returned**, never on a TOTP default. A student enrolled
  in email OTP — the alternative that exists precisely for students without a smartphone (`prd.md` NFR-2) —
  would otherwise be shown a screen asking for an authenticator app they do not have. The lockout countdown
  is driven by `details.locked_until` from the `423`, not by counting failed attempts in the tab, which a
  reload would reset. **[PROPOSED — confirm]** there is no endpoint that sends or resends an OTP *during* a
  challenge, so the only alternative factor the client can honestly offer is the backup code; if a
  challenge-time send endpoint is added, email OTP joins the same chooser unchanged.

- **One-time codes use `type="text"` with `inputmode="numeric"`, never `type="number"`.** A number input
  drops a leading zero in several engines, renders spinners, and ignores `maxlength` entirely — a code of
  `012345` silently becomes `12345`. `autocomplete="one-time-code"` is set so mobile keyboards offer the code
  from the notification shade; a backup code opts out, because it is not a one-time code to the browser.

- **Countdowns are announced coarsely, not per second.** `prd.md` A11Y-1 requires a countdown to be
  announced rather than ticking silently, but putting `aria-live` on the seconds interrupts a screen-reader
  user continuously for the whole lockout. The visible mm:ss readout is `aria-hidden` and a separate live
  region announces "about N minutes left", changing only when the minute changes.

- **The site chrome is scoped by route group, not toggled per page.** `[locale]/(site)` renders the nav and
  footer; `[locale]/(auth)` renders neither, because the login and 2FA prototypes both suppress them and the
  reason is sound — a half-authenticated user has nowhere legitimate to navigate to, and the marketing nav
  mid-challenge is an invitation to abandon the flow. Route groups add no path segment, so no URL changes.
  The 404 sits outside both groups and renders its own chrome: a dead end is the page that most needs a way
  out.

- **Mock layer.** The frontend is built before the backend exists, against handlers matching these contracts
  field-for-field, switched by a single env var. Mock response types are derived from the same definitions
  the live client uses, so drift is a type error rather than a runtime surprise.

- **Budget (`prd.md` A11Y-2).** Fonts self-hosted and the Urdu face loaded only for `ur`; Tailwind compiled
  at build time; reference data cached rather than refetched per form step; target LCP under 3 s on a
  mid-tier Android over Slow 3G.

- **No icon font.** The mockups pulled Material Symbols from Google at runtime — a third-party request in
  the critical path, for decoration. Icons are inline SVG instead, marked `aria-hidden` since each sits
  beside a real text label.

- **Prototypes are built at full fidelity, motion included.** The supplied prototype is the visual
  specification, not a content reference: grid spans, column ordering, aspect ratios, sticky behaviour,
  illustrative preview panels, and the animation — scroll reveal, stagger, parallax, hover lift, pulse, and
  the animated hero backdrop. Where a prototype exceeds the design system, the token set is **extended**
  rather than the design downgraded: the landing needs display type at 48–56px, which the `DESIGN.md`
  scale (max 32px) does not cover, so `display-sm/md/lg` were added and labelled as an extension.

- **Motion degrades, it does not simplify.** Every animation is disabled under `prefers-reduced-motion`,
  and scroll-reveal in particular resolves to fully visible rather than being left mid-transition. The
  reveal CSS is scoped behind a `data-reveal-ready` attribute set by the controller on mount, so a visitor
  whose JavaScript fails sees content rather than a permanently transparent page. The WebGL hero backdrop
  falls back to a CSS gradient when WebGL is unavailable or the shaders fail to compile, caps its backing
  store on high-DPI screens, and stops rendering while the tab is hidden — a backgrounded tab must not burn
  a phone battery on an invisible animation (`prd.md` A11Y-1, A11Y-2).

- **Marketing copy is bound by the RBAC matrix too.** The landing page describes what a parent gets as
  progress visibility, and states that a child's tutoring conversations stay private. The mockups' parent
  dashboard offered a session-replay control that `prd.md` §4.2 forbids; the marketing must not advertise
  the capability either, so a component test asserts the parent copy says so.

- **Prototype links whose product area does not exist yet resolve to a coming-soon page**, not to `href="#"`
  and not by deletion. "Institution Demo", the Curriculum / Tutor / Progress nav entries, the footer policy
  links and the auth screens' Help / Privacy / Terms all land there. A dead anchor reads as broken software,
  and removing the link loses the prototype's navigation; a page that says "this is being built" is honest
  about both. *(Supersedes v0.3.2's "Removed: the Institution Demo call to action".)* **[PROPOSED — confirm]**
  whether an institutional enquiry route is wanted at all — `prd.md` §15 CL-6 has institutions attach through
  classroom join codes, with no separate institutional route in v1.

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

- **(a) Identity & RBAC:** `app_user(id, email🔑, password_hash, role⋈enum, status, ts)` *(table name `app_user`; "user" is reserved in Postgres)*, `student_profile(user_id🔗, board, class_level, **student_group**, medium, language_pref, CHECK class/group pairing)`, `teacher_profile(user_id🔗)`, `teacher_subject_scope(teacher_id🔗, subject_id🔗, PK(teacher_id,subject_id))` — **explicit M:N**: report scoping joins through this (a subject is per board×class, §b), `parent_profile(user_id🔗)`, `admin_profile(user_id🔗, scope)`, `guardian_link(parent_id🔗, student_id🔗, status⋈enum, verification_method, verified_at, CHECK(parent_id≠student_id), UNIQUE(parent_id,student_id))`, `auth_token(id, user_id🔗, kind, hash, revoked, expires_at)` — `token_kind` extended with `two_factor_email_otp` and `two_factor_pending`, `two_factor_enrollment(user_id🔗🔑, method⋈enum{totp,email_otp}, status⋈enum{pending,active,disabled}, totp_secret_encrypted bytea, confirmed_at, last_used_at, last_used_counter, failed_attempts, locked_until)` — one per user; secret **encrypted at rest**, `two_factor_backup_code(id, user_id🔗, code_hash, used_at, UNIQUE(user_id,code_hash))` — 10 per enrolment, **argon2id-hashed**, single-use, **8 alphanumeric characters compared case-insensitively**, `subscription_plan(code🔑, name, price_minor, currency, billing_interval, is_active)` — reference data, one row in v1; prices in **minor units** so money is never floating point; `billing_interval` is prefixed because `interval` is a Postgres type name, `subscription(id, user_id🔗, plan_code🔗, status⋈enum{trialing,active,past_due,canceled,expired}, trial_ends_at, current_period_end, UNIQUE(user_id), CHECK(status<>'active' OR current_period_end IS NOT NULL))` — **one per user**; `trial_ends_at` defaults to 14 days **in the schema**, which is the single definition of trial length, `oauth_identity(id, user_id🔗, provider⋈enum{google,microsoft}, provider_user_id, UNIQUE(provider,provider_user_id), UNIQUE(user_id,provider))` — reserved for the deferred FR-A6; `provider_user_id` is the provider's opaque subject claim, not an email, because emails change and are reusable.
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
| `20260801120000_initial_schema.sql` | Extensions, enums, 45 tables (incl. two-factor auth), the admin 2FA status view, constraints, indexes, triggers, partitions |
| `20260801120100_rls_policies.sql` | `app_backend` role, RLS helper functions, **68 policies** — 56 written out plus 12 generated in a `DO` loop over the reference tables (§6.8, §6.9) |
| `20260801120200_seed_reference_data.sql` | Boards, class levels, subjects (76 rows) and 160 elective-group mappings |
| `20260802120000_subscriptions_and_oauth.sql` | `subscription_plan`, `subscription`, `oauth_identity` — **taking the schema to 48 tables**; two enums; the Rs. 999 `standard` plan seed; grants and 5 RLS policies (§6.8) |
| `20260802140000_reference_read_and_auth_lookups.sql` | `SELECT` policies for the six reference/curriculum tables, which the blanket RLS loop had left readable by nobody; `SECURITY DEFINER` lookups for the pre-auth login and refresh paths |
| `20260802140100_token_kind_enrollment.sql` | `two_factor_enrollment` added to `token_kind`, separating the 900 s enrolment token from the 300 s pending token (Postgres cannot use an enum value added in the same transaction, hence its own file) |
| `20260802150000_guardian_gate_and_partition_rls.sql` | Guardian-gate helper functions; RLS on the `audit_log` and `api_request_log` default partitions |
| `20260803090000_guardian_link_write_boundary.sql` | **The anti-forgery boundary (§3.1, §6.8):** `app.reinvite_guardian_link`; `guardian_link_create` restricted to `pending`; `guardian_link_update` made parent-only and barred from writing `verified` |
| `20260803120000_2fa_email_password_lookups.sql` | `SECURITY DEFINER` lookups for 2FA enrolment/challenge, email verification and password reset |
| `20260803160000_2fa_lockout_and_email_locale.sql` | Enrolment no longer clears `failed_attempts`/`locked_until`, so restarting cannot launder a lockout; `activate_2fa` records the consumed step; `check_token_status` distinguishes a **spent** token from a **lapsed** one (§7.3) |
| `20260803180000_login_2fa_lookup.sql` | `app.lookup_2fa_for_login` — login read its 2FA row unbound under RLS, so every enrolled user was silently returned to enrolment |

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
| `guardian_link.status` | pending→(verified\|revoked) | 9–10 tutor access requires `verified`; only an authenticated **parent** account can verify (§3.1) |
| `subscription.status` | trialing→(active\|expired); active→(past_due→(active\|canceled))\|canceled; expired→active | learning access requires `trialing` or `active`; **absence of a row is not a state** — it is no access (`prd.md` MON-2) |
| *`onboarding_state`* **(derived, no column)** | email_verification_pending→two_factor_enrollment_pending→[guardian_link_pending]→active **⇄** plan_selection_pending | computed per request by the precedence table in §3.1. **The only non-monotonic machine here** — a lapsed trial returns an active student to plan selection, so consumers must re-evaluate rather than cache |
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

**Policy model** — **73 policies**: 68 from the initial policies migration (56 written out plus 12 generated in a `DO` loop over the reference tables) and 5 added with subscriptions/OAuth. Helper functions live in the `app` schema and are `SECURITY DEFINER` to avoid recursing through the very policies that call them.

| Data | Rule |
|---|---|
| Own profile / progress / attempts | `student_id = app.current_user_id()` |
| Parent → child | `app.is_verified_guardian_of(student)` — requires `guardian_link.status='verified'` |
| `guardian_link` **writes** | Either participant may INSERT, but only as `pending`; only the **parent** may UPDATE, and never to `verified`. `verified` is therefore reachable through exactly one path — `app.confirm_guardian_link`, which demands an unexpired one-time `guardian_invite` token — and a parent can withdraw consent without being able to grant it. The student's re-invite reset goes through `app.reinvite_guardian_link` for the same reason (§3.1 anti-forgery; migration `20260803090000`) |
| Teacher → student | `app.teaches_student_subject(student, subject)` — active enrollment in the teacher's space **and** the subject in `teacher_subject_scope` |
| Chat (`chat_session`/`message`/`visual_aid`) | **Owner only.** No teacher, parent, or admin read path exists |
| `question_key` | **No policy at all** — the app role can never read answer keys (NFR-8 database backstop) |
| `audit_log`, `api_request_log` | Insert-only from the app, admin read; no UPDATE/DELETE policy, so the trail is tamper-evident |
| Curriculum taxonomy | Readable by any authenticated user; admin writes |
| `subscription_plan` | Readable by any authenticated user (the plan screen renders during onboarding, so a session always exists); admin writes |
| `subscription` | **Owner only**, plus **admin `SELECT` only**. Admins get read for provisioning and billing support, deliberately not `FOR ALL` — an admin must not be able to grant a paid subscription outside the payment path. **No parent policy:** parents pay for nothing in v1, and adding guardian read here would widen `prd.md` §4.2 without a requirement behind it |
| `oauth_identity` | **Owner only.** No admin path — `provider_user_id` is an identifying external subject and no support workflow needs it |

Enabling RLS on every `public` table also closes Supabase's PostgREST exposure of unprotected tables.

### 6.9 Two-factor authentication (SEC-14)

Mandatory for **every role**. A password alone is never sufficient for a session.

**Schema** — folded into `supabase/migrations/20260801120000_initial_schema.sql` (safe because no database has had the migrations applied yet); RLS policies live in the policies migration:

```sql
CREATE TYPE two_factor_method AS ENUM ('totp','email_otp');
CREATE TYPE two_factor_status AS ENUM ('pending','active','disabled');
ALTER TYPE token_kind ADD VALUE 'two_factor_email_otp';
ALTER TYPE token_kind ADD VALUE 'two_factor_pending';

CREATE TABLE public.two_factor_enrollment (
  user_id               uuid PRIMARY KEY REFERENCES public.app_user(id) ON DELETE CASCADE,
  method                two_factor_method NOT NULL,
  status                two_factor_status NOT NULL DEFAULT 'pending',
  totp_secret_encrypted bytea,        -- AES-256; NULL when method = 'email_otp'
  confirmed_at          timestamptz,
  last_used_at          timestamptz,
  last_used_counter     bigint,       -- replay guard: reject a code already spent
  failed_attempts       smallint NOT NULL DEFAULT 0,
  locked_until          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_totp_has_secret
    CHECK (method <> 'totp' OR totp_secret_encrypted IS NOT NULL)
);

CREATE TABLE public.two_factor_backup_code (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES public.app_user(id) ON DELETE CASCADE,
  code_hash  text NOT NULL,           -- argon2id; plaintext shown once, never stored
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_backup_code UNIQUE (user_id, code_hash)
);
CREATE INDEX ix_backup_code_unused
  ON public.two_factor_backup_code(user_id) WHERE used_at IS NULL;
```

RLS: both tables are **owner-only** (`user_id = app.current_user_id()`), with admin read limited to `status`/`locked_until` for support — never to secrets or code hashes.

**Enrolment.** After email verification, the user picks TOTP (QR + manual secret) or email-OTP, confirms one live code (`status → active`), and is shown **10 backup codes exactly once**. Access is withheld until `status = 'active'`.

**Login (two-step).**
```
password ok ──▶ 200 {status:"two_factor_required", pending_token} (≈5 min, no business scope)
                     │
                     ▼  /2fa/verify  (TOTP | email-OTP | backup code)
                 access + refresh JWT
```

**Login response shape.** A correct password always returns `200` with one of three
`status` values — never a session:

| `status` | Also returns | Client action |
|---|---|---|
| `email_verification_required` | masked email | Send to "verify your email" screen |
| `two_factor_enrollment_required` | `enrollment_token`, `expires_in` | Send to 2FA enrolment |
| `two_factor_required` | `pending_token`, `method`, `expires_in` | Send to 2FA challenge |

A **wrong** password returns `401 UNAUTHENTICATED`, worded so it never reveals whether the
email exists. Using `200` here is deliberate: the request succeeded and the credentials were
valid, so a `4xx` would force clients to distinguish "wrong password" from "next step needed"
by parsing an error code — fragile, and easy to render as a spurious failure.

**Verification rules.**
- TOTP: RFC 6238, 6 digits, 30 s period, **±1 window** tolerated for clock skew.
- **Replay guard:** `last_used_counter` rejects a code already consumed in its window.
- Backup codes: constant-time hash comparison; consumed by setting `used_at`.
- Email-OTP: 6 digits, ≤10 min TTL, single-use, stored hashed in `auth_token`.
- **Rate limiting:** a 6-digit code is only 10⁶ combinations, so verification is throttled per user and per IP; `failed_attempts` drives a **temporary** `locked_until`, never a permanent lock.
- Every attempt — success or failure — writes to `audit_log`.

**Recovery ladder** (deliberate, to protect students without smartphones — NFR-2):
1. Alternate method (email-OTP if TOTP unavailable)
2. Backup code
3. Admin-assisted reset (`/api/admin/users/{id}/2fa/reset`) with identity verification, fully audited

**Secret handling.** The TOTP secret is encrypted with an application-held key (not stored in the database) and is returned **only** in the enrolment response — never re-readable afterwards. Backup codes exist in plaintext only in the single response that issues them.

### 6.10 CI/CD hardening

GitHub Actions on every PR: unit/integration tests, **Semgrep** static analysis, **OPA policy tests**, the **Secure Skills & MCP scanner**, container build + **sigstore** signing. Protected `main`; only lead merges; secrets encrypted.

A separate `frontend.yml` workflow runs typecheck, lint, format check, unit/component tests and build on any change under `frontend/`. It runs against the mock layer, so it needs no backend and stays green while the backend tracks are still in progress. It uses `npm ci` rather than `npm install`, so a lockfile that disagrees with `package.json` fails the build instead of silently resolving something different. No browser E2E job — that suite belongs to the backend track (§9.5).

**Dependency overrides (frontend).** Next 16.2.12 pins `postcss` to exactly `8.4.31` and `sharp` to
`^0.34.5`; both carry high-severity advisories. `npm audit fix --force` "resolves" this by installing
**next@9.3.3** — a seven-major downgrade, which is not a fix and must never be run here. Instead
`package.json` carries `overrides` lifting both to patched lines, which takes the audit to zero without
touching the framework version. Typecheck, lint, tests and build were re-verified after applying them.
These overrides should be **removed** once Next ships a release pinning patched versions — a stale override
silently holds a transitive dependency back.

### 6.11 Client-side security (frontend)

- **`qr_svg` is server-supplied markup and must not be injected as HTML.** The 2FA enrolment response carries
  a rendered SVG; interpolating it into the DOM would execute any `<script>` it contained. It is rendered as
  a **base64 `data:` URI inside an `<img>`**, where SVG is processed in a restricted mode that runs no
  scripts and issues no external requests. This is stricter than the DOMPurify path used for agent-generated
  visuals (§3.10) and is appropriate because the asset has a fixed, known shape.
- **Token storage** — access token in memory, refresh token in an httpOnly cookie; never `localStorage`,
  `sessionStorage`, a readable cookie, or a query string (§3.10).
- **No secrets in client-visible configuration.** Anything prefixed `NEXT_PUBLIC_` is compiled into the
  bundle and is therefore public by definition.
- **Response headers** set at the edge: `Content-Security-Policy`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
  - **`script-src` carries `'unsafe-inline'`. This is a recorded deviation, not an oversight** — read §14.5
    before removing it. The App Router streams its React payload through inline `<script>` elements; a bare
    `script-src 'self'` blocks them, React never hydrates, and the entire application ships as inert HTML
    with no console output and every asset returning `200`. A per-request nonce is the correct fix and is
    unavailable here, because the auth routes are prerendered per locale at build time and a nonce requires
    per-request rendering. Revisit if those routes ever become dynamic for another reason.
  - The directives that matter most for an authentication surface are unaffected: `frame-ancestors 'none'`
    blocks clickjacking of the login and 2FA screens, `form-action 'self'` stops a form being retargeted at
    another origin, `base-uri 'self'` stops a `<base>` element rewriting every relative URL, `connect-src`
    confines API calls, and `img-src 'self' data:` still admits only the 2FA QR.
- **Credential-manager compatibility** — correct `autocomplete` values (`username`, `current-password`,
  `new-password`, `one-time-code`). This is a security control, not polish: the target cohort shares devices
  (`prd.md` §3.1), and fields a password manager cannot fill push users toward weak, memorable, reused
  passwords.
- **No account enumeration** — registration, login and password-reset responses must not reveal whether an
  address exists, by body, status code, or timing.

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
| GET | `/api/subscription` | Yes | Student | Current plan, `status`, `trial_ends_at`, `current_period_end` (FR-A5) |
| POST | `/api/subscription/select` | Yes | Student | Choose the plan; clears `plan_selection_pending` once the subscription is active |

### 7.3 Error model

Standard envelope: `{ "error": { "code": "...", "message": "...", "details": {...} } }`.

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | bad input; `details.fields` carries per-field messages |
| 400 | `INVALID_TOKEN` | malformed or unknown verification / reset / invite token |
| 410 | `TOKEN_EXPIRED` | token was valid but has lapsed; offer a resend |
| 401 | `UNAUTHENTICATED` | missing/expired token — **also the only response meaning "wrong password"** |
| 401 | `TWO_FACTOR_INVALID` | Wrong or expired TOTP / email-OTP / backup code |
| 401 | `PENDING_TOKEN_EXPIRED` | the short-lived 2FA challenge token lapsed; restart at login |
| 423 | `TWO_FACTOR_LOCKED` | Too many failed attempts; retry after `details.locked_until` |
| 403 | `GATE_PENDING` | Class 9–10 parental link not verified |
| 403 | `SUBSCRIPTION_REQUIRED` | trial lapsed, no active subscription (FR-A5) |
| 403 | `FORBIDDEN_SCOPE` | role/subject/ownership violation |
| 409 | `EMAIL_ALREADY_REGISTERED` | address already has an account |
| 409 | `GUARDIAN_ALREADY_LINKED` | this parent↔student link already exists |
| 409 | `ATTEMPT_EXISTS` | second quiz attempt blocked |
| 422 | `INVALID_CLASS_GROUP` | elective group is not valid for the chosen class |
| 422 | `SELF_LINK_FORBIDDEN` | student used their own address as the parent's |
| 422 | `GUARDIAN_NOT_FOUND` | no **active parent** account uses that address — the parent signs up first (§3.1), so this is the ordinary outcome of the gate screen, not an edge case, and the client must render a next step rather than a generic failure |
| 422 | `NOT_GROUNDED` | no confident curriculum answer (degrade) |
| 429 | `RATE_LIMITED` | over limit; `Retry-After` header |
| 503 | `MODEL_UNAVAILABLE` | fallback path engaged |

*(Table repaired in v0.3.7 — two explanatory paragraphs sat between `GUARDIAN_NOT_FOUND` and `NOT_GROUNDED`, so the last three codes rendered as a separate, header-less fragment. They now follow the table.)*

**`INVALID_TOKEN` vs `TOKEN_EXPIRED` is not a coin toss.** A token that was already *used* is `400 INVALID_TOKEN`. `410` is what makes the client offer a resend, and offering one for a link that already worked sends the user round a loop they have finished. Only an **unused, lapsed** token is `410`. `app.check_token_status` returns `token_revoked` precisely so the two can be told apart.

**No endpoint invents a code.** `/2fa/resend` against a TOTP enrolment answers `400 VALIDATION_ERROR` with `details.fields`, not a bespoke `INVALID_METHOD`: a code outside this table reaches the client as an unrecognised string and renders as "something went wrong".

**`POST /api/auth/password/change` answers `401 UNAUTHENTICATED` when the *current* password is wrong** — not a new `WRONG_PASSWORD` code, by the rule above and by the `UNAUTHENTICATED` row's own "also the only response meaning 'wrong password'". *(Stated explicitly in v0.3.8, because it has a consequence no other route has.)*

> ⚠️ **This is the one route where both meanings of `401 UNAUTHENTICATED` are live at once** — an expired access token *and* a wrong password. Clients keep an allow-list of 401 codes worth retrying after a token refresh, and `UNAUTHENTICATED` is necessarily on it. **A client must therefore opt this route out of refresh-and-retry**, or every mistyped password silently fires a token refresh and replays the request. The reference client does so with `noRetry: true` (`lib/api/endpoints.ts`). The guard that shields `/2fa/confirm` — "the credential travelled as `bearer`" — does not apply here, because this credential travels in the body.

Rate-limited responses include `Retry-After` + `X-RateLimit-*` headers (SEC-3).

**Session lifetime (v0.3.8).** A refresh chain has an **absolute ceiling** of
`SESSION_ABSOLUTE_TTL_DAYS` (default 14) measured from when the chain BEGAN, carried forward across
every rotation — without it, rotation extends a session for ever, seven days at a time, and no
session anybody keeps using ever expires. ⚠️ The real ceiling is that **plus up to one
`JWT_ACCESS_TTL_MINUTES`**, because a refused rotation stamps nothing and the access token already
issued lives out its own TTL; the setting is not a hard 14 days and must not be described as one. A
ceiling that does not exceed `JWT_REFRESH_TTL_DAYS` is refused at boot, since the individual token
would expire first on every chain and the cap could never fire.

**Ending live sessions.** Password change, password reset and detected token reuse stamp
`app_user.sessions_invalidated_at`, and every access token issued at or before it is refused.
Revoking refresh tokens alone does not do this — it ends only the ability to obtain a NEW access
token, leaving the one already held valid for up to its TTL.

**Refresh rotation is atomic, and a race is not a theft.** Two concurrent refreshes presenting the
same token cannot both succeed. The loser receives a plain `401 UNAUTHENTICATED` and **the family is
not revoked**, provided the token was revoked moments earlier and a live sibling of the same chain
still exists; a replay outside that window, or with no live sibling, is reuse and revokes the family.
⚠️ A client's single-flight guard is typically per browser TAB, so two tabs are enough to collide —
treating that as theft signs the user out of every device. The loser's 401 is self-healing, because
the winner's `Set-Cookie` has already replaced the token. Race events are audited as
`refresh_token_race_detected`.

**Retention (§5.9).** `auth_token` rows are deleted **30 days after expiry**, not on expiry: reuse
detection reads the revoked row, so deleting it early turns a replayed stolen token into a silent 401
instead of a family revocation.

**Refusals follow the onboarding order (v0.3.8).** An account that is not yet email-verified is
answered `email_verification_required` even when it carries a live second-factor lockout. The
previous order returned `423 TWO_FACTOR_LOCKED` first, which told the user to wait out a lockout on
a factor they had not reached and disclosed that the account had 2FA state at all. Verify, then
enrol, then challenge — the refusals must match the journey.

**Outgoing email is dispatched only after the transaction commits (v0.3.8).** A verification or
reset link is queued against the session that minted its token and released when that session
commits; a rollback discards it. Sending during the open transaction meant a request that failed
late delivered a link for a token that no longer existed — unrecallable, and answerable only with
`INVALID_TOKEN`. Signing in to an `email_otp` account also sends the code, which it previously did
not: the challenge screen said one had been sent while nothing had.

**Every credential-bearing field is length-bounded (v0.3.8).** Passwords, tokens and codes all carry
a maximum, because an unbounded string reaching argon2 is an unbounded amount of work on the one
endpoint an unauthenticated caller can hammer. ⚠️ Fields carrying an EXISTING password — login, and
the current password on change — are bounded above only: a minimum there would refuse any account
whose password predates a policy change, and would answer `400` where every other wrong password
answers `401`.

**Clients branch on `code`, never on `message`** — messages are localized and will change. An unrecognised
code must still render a usable state rather than a blank screen (`prd.md` §20).

**`SUBSCRIPTION_REQUIRED` deliberately mirrors `GATE_PENDING`** — both are `403`s meaning "authenticated, but
an onboarding precondition is unmet", and both are handled by the client the same way: redirect to the step
`onboarding_state` names. `402 Payment Required` was considered and rejected as a needless second pattern for
a case the gate convention already covers.

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
| `EMAIL_PROVIDER` | `logging` | `logging` (dev/CI) · `sendgrid` (production, chosen v0.3.9) · `resend` (retained, unused). A **`Literal`** — a value outside the three is refused at boot, not ignored (A3). `logging` is refused in production |
| `SENDGRID_API_KEY` | — | SendGrid Web API key (`SG.…`); required when `EMAIL_PROVIDER=sendgrid` |
| `EMAIL_FROM` | — | Required by **every** real provider; the application refuses to start without it. For SendGrid: a verified Single Sender, or an address on an authenticated domain. ⚠️ An unauthenticated single sender delivers but commonly lands in **spam** — domain authentication (SPF/DKIM) is the fix, and it is a DNS change |

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
| 2FA enforced (SEC-14) | Correct password, no 2FA challenge | `200 {status:"two_factor_required"}` + pending token; **no session issued**; pending token cannot call business endpoints |
| 2FA enrolment gate | Verified user with no active factor logs in | `200 {status:"two_factor_enrollment_required"}` + enrollment token; no session until enrolment completes |
| 2FA methods | Verify by TOTP, by email-OTP, by backup code | All three grant a session; email-OTP works without a smartphone |
| 2FA replay | Re-submit a TOTP code already used | Rejected by the replay guard |
| 2FA backup code | Reuse a consumed backup code | Rejected; code is single-use |
| 2FA lockout | Repeated wrong codes | `423 TWO_FACTOR_LOCKED`, temporary; unlocks after `locked_until` |
| 2FA secret exposure | Read enrolment via API after setup | Secret never returned; only status is visible |
| 2FA admin reset | Admin resets a locked-out user | Succeeds with identity verification and writes to `audit_log` |
| Self-update | Ingest unsigned source | Quarantined; not in KB |

### 9.3 AI eval harness
- **Retrieval groundedness** (answer cites retrieved curriculum) · **answer correctness** vs board answer keys · **BKT calibration** (predicted vs held-out outcomes) · **Urdu-TTS intelligibility** sample. Targets = PRD §22 KPIs.

### 9.4 Security tests
Guardrail-bypass attempts (LLM01/05), rate-limit 429 (LLM10), quiz-tamper (keys server-side), authz matrix (teacher cross-subject, parent write, 9–10 gate bypass, cross-student read), provenance quarantine (LLM04), OPA manifest enforcement.

### 9.5 Frontend test matrix

Runs entirely against the mock layer, so it is green before any backend endpoint exists.

| Level | Coverage |
|---|---|
| **Unit** (Vitest) | `onboarding_state` → route for all five states × four roles · error-envelope parsing · the 401 retry allow-list (must **exclude** `TWO_FACTOR_INVALID` and `PENDING_TOKEN_EXPIRED`) · RTL locale predicate · BCP-47 validity of every routing locale · class→group lookup where the record is keyed by string and the class levels are numbers · design-token assertions pinning the resolved `DESIGN.md` conflicts |
| **Component** (React Testing Library) | Elective group clears when class changes · login advances on each `status` and errors only on `401` · 2FA method switching across TOTP / email-OTP / backup code · backup-code acknowledgement gates Continue · every error code renders its designed state · `NAV_BY_ROLE` renders exactly the permitted items per role |
| **Flow** (component-level, multi-screen, against mocks) | Class-9 journey through signup → verification → 2FA → gate → dashboard · Class-11 never reaches the gate · a lapsed trial redirects an active session to plan selection · 401 → refresh → retry |

**E2E browser tests are owned by the backend track, not the frontend** (§9.1). That is a deliberate split,
and it has a cost the frontend has to cover: browser-level E2E cannot run until the backend exists, so it
gives no signal during the frontend phases. The **Flow** row above exists to fill that gap — those are
component-level tests that mount several screens in sequence against the mock layer, so the journeys that
matter are still guarded while the backend is being built. Without that row, the multi-screen behaviour
(which is where onboarding bugs actually live) would go untested for the whole sprint.

**The highest-value regression test is the parent navigation assertion** — that the parent surface renders no
tutor, chat-replay, planner-write or assessment control. That is the `prd.md` §4.2 boundary expressed as
code, and a shared component tree makes it the single easiest thing to reintroduce by copying.

**Accessibility and budget gates** (`prd.md` A11Y-1/A11Y-2), enforced in CI rather than by review: automated
a11y scan clean on every route; keyboard-only traversal of signup → login → 2FA; every screen at 360 px;
first-load JS within budget.

**Two rules are enforced by tests rather than by review, because both are invisible until someone reads the
page in the wrong language or with the wrong account:**

- **The RTL sweep.** Every source file's class strings are scanned for physical direction properties —
  `ml`/`mr`, `pl`/`pr`, `left`/`right`, `text-left`/`text-right`, `border-l`/`border-r`. All fifteen
  prototypes are written physically, so a class copied verbatim looks perfect in English and silently breaks
  the Urdu layout. The rule (`prd.md` I18N-4) is that mirroring uses logical properties only, and the test is
  what makes that true rather than aspirational.
- **The parent-navigation assertion**, described above.

**A production build must be opened in a browser and interacted with before a phase is done.** This is not
ceremony: `tsc`, `eslint`, `vitest` and `next build` all passed for five phases while the shipped artefact was
completely inert (§14.5). Unit and component tests render React directly and never see a Content-Security-
Policy, a service worker, or a hydration failure, so none of them can catch a build that does not come alive.
`npm start`, load a route, type into a field, press a button.

---

## 10. Future Enhancements
- **P1 build-out:** full assessment/classroom/security layer (already designed here).
- **P2:** self-updating pipeline breadth; broaden the full PCTB+STBB × 9–12 × all-subjects matrix; admin depth.
- **Stretch:** diffusion image generation; guardrail-moderated student↔teacher chat; advanced analytics; additional boards.

---

## 11. Maintenance and Support

### 11.1 Version history

See the **Document History** table at the head of this document. *(Through v0.3.6 this section held a
second, one-row table claiming the document was v0.1.0, contradicting the nine rows above it. Removed in
v0.3.7 — one document states its version in one place.)*

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
| **Row Level Security** designed and implemented (68 policies, `app_backend` role, session-variable context) | Defense-in-depth for minors' data | §6.8, SEC-13 |
| Subjects **6 → 10**, per-class lists, **elective groups** (`student_group`) | Real board structure | §5.3a/b, PRD §2.4.1 |
| Two branches → **four `content_strategy` values** | English and religious content need distinct handling | §3.4, §4.6, PRD §2.4.2 |
| **Religious-verbatim mode** — generation node disabled for Quran Translation | FR-17; ethical + accuracy requirement | §4.6, §9.2 |
| `subject_group`, `class_level`, `agent_component`, `question_key` | Normalization; polymorphic FK removal; NFR-8 backstop | §5.2, §5.3 |
| `uuidv7()` → `gen_random_uuid()`; `audit_log` composite PK | **Both would have failed on PostgreSQL ≤17** | §5.4 |
| Inline DDL replaced by a pointer to `supabase/migrations/` | Prevent schema drift between doc and code | §5.4 |

### 14.2 Changes in v0.3.0

| Change | Driver | Where |
|---|---|---|
| **2FA mandatory for all roles** — TOTP primary, email-OTP alternative, hashed single-use backup codes | SEC-14 / FR-A4 | §3.1, §6.9 |
| Login split into **two steps**; a password yields only a short-lived pending-2FA token | Stolen passwords must not yield sessions | §3.1, §6.9 |
| New tables `two_factor_enrollment`, `two_factor_backup_code`; two new `token_kind` values | Schema for SEC-14 (Track D migration) | §5.3a, §6.9 |
| Replay guard, ±1 window skew tolerance, throttling, **temporary** lockout | 6-digit codes are brute-forceable | §6.9 |
| **Recovery ladder** — alternate method → backup code → audited admin reset | Class 9–10 students may lack a smartphone (NFR-2 tension) | §6.9, PRD §24 |
| 4 new error codes (`TWO_FACTOR_*`) | Explicit client handling | §7.3 |

**Open question on 2FA:** whether to offer "remember this device" (e.g. 30 days) to reduce friction for young students. It weakens the control on shared devices — which is exactly the cohort in question — so it is **not** designed in. **[PROPOSED — confirm]**

**Still open (decisions, not defects):** deployment target §2.4, vector DB choice §5.5, GPU spec, similarity threshold `SIM_THRESHOLD`, and the Class-11 ICS subject list (PRD §2.5).

### 14.3 Changes in v0.3.2

Seventeen decisions, taken while auditing the supplied UI mockups against this document and `prd.md`. The
audit is what surfaced most of them: the mockups implemented a parental gate running the wrong way, an
unspecified subscription flow, no 2FA enrolment screen at all, and one student sidebar pasted into all three
role dashboards.

| # | Change | Driver | Where |
|---|---|---|---|
| 1 | Parental gate fixed as a **student-initiated email invite**; code redemption rejected | A code the student types is not out-of-band, reopening §14 finding 3 | §3.1, PRD §4.3 |
| 2 | `guardian/confirm` becomes **authenticated** — the parent signs up first | Only a distinct, separately authenticated account makes the signal out-of-band | §3.1 |
| 3 | Access is **paid**: one tier, Rs. 999/month, **no free tier** | Product decision | PRD §2.6 |
| 4 | **14-day trial**, defined once in the schema default | One source of truth for trial length | §5.3a, §5.4 |
| 5 | `onboarding_state` gains **`plan_selection_pending`** (students, after the gate) | FR-A5 | §3.1 |
| 6 | `onboarding_state` documented as **derived**, with an explicit precedence table | It has no column; four tracks were about to reimplement it differently | §3.1 |
| 7 | Onboarding is **non-monotonic** — a lapsed trial returns an active student to plan selection | The obvious "check once then trust" guard strands the user | §3.1, §5.8 |
| 8 | Missing subscription row **fails closed** | A failed insert must not grant indefinite free access | §3.1, PRD MON-2 |
| 9 | `email/verify` returns `access_token` + `enrollment_token`, **scoped to onboarding routes** | Otherwise email verification alone becomes a full login and 2FA is bypassable | §3.1 |
| 10 | `2fa/confirm` returns `access_token`; both enrolment endpoints take `enrollment_token` **in the body** | Matches how `/2fa/verify` already carries `pending_token`; avoids an immediate second login | §3.1, §7.3 |
| 11 | **Teacher tutor access removed** | `prd.md` §4.2 said "✅ own testing" while `/api/tutor/ask` has always been student-scoped | §3.2, PRD §4.2 |
| 12 | Navigation derived per role from one `NAV_BY_ROLE` map | The mockups gave parents a tutor-session replay button, which RLS and the matrix both deny | §3.10, §9.5 |
| 13 | Student navigation gains **My Classes** | `prd.md` §4.2 grants a right to leave any space; there was no UI for it | §3.10 |
| 14 | `qr_svg` rendered as a data-URI `<img>`, never injected as HTML | Server-supplied markup would otherwise execute scripts | §6.11 |
| 15 | Access token **in memory**, refresh in httpOnly cookie | v0.3.1 said "tokens in httpOnly cookies", which the client cannot read | §3.10, §6.11 |
| 16 | Three tables + 5 RLS policies; admin gets **read-only** on `subscription` | An admin must not grant paid access outside the payment path | §5.3a, §6.8 |
| 17 | Seven error codes added; RTL rule and frontend test matrix specified | Codes existed in the contract but were never catalogued | §7.3, §9.5, PRD I18N-4 |

**Corrected during Phase 3 — the class/group key hazard was described wrongly.** Earlier versions of this
document, `prd.md` and the frontend plan all claimed `groups_by_class[9]` returns `undefined` because the
record is keyed by string. That is false: JavaScript coerces the key, so `[9]` and `['9']` are the same
lookup, and a test written to assert the wrong behaviour is what exposed it. The hazard is real but sits
elsewhere — **comparison, in either direction, where no coercion happens**:
`Object.keys(groups_by_class).includes(9)` is `false`, a `Set` of those keys never matches a number, and
`class_levels.includes('9')` is `false` going the other way. Signup must normalise with `String()` before
any comparison or collection lookup. All three documents now say so.

**Found during Phase 2 implementation — `roman_ur` is not a usable web locale.** The contract's language
value was carried straight into routing, and it broke: `Intl` rejects the tag with `RangeError`, and
`<html lang="roman_ur">` conveys nothing to assistive technology. The web layer now uses **`ur-Latn`** and
maps at the API boundary (§3.10, `prd.md` I18N-5). The database enum and every API payload are unchanged, so
no other track is affected. A test asserts every routing locale is a valid BCP-47 tag, which is what would
have caught this on day one.

**Amended during Phase 1 implementation:** browser E2E was moved out of the frontend and into the backend
track. The frontend keeps unit and component levels and adds a **Flow** level — multi-screen component tests
against the mock layer — because browser E2E cannot run until the backend exists and would otherwise leave
the onboarding journeys untested for the whole sprint (§9.5).

**Corrections to earlier versions found during this pass:** the RLS policy count was stated inconsistently —
54 in §6.8 and §14.1, 56 in §5.4. The applied total is **68** (56 written out plus 12 generated in a `DO`
loop), and **73** after this migration; all three places now agree. The endpoint table in §3.1 was also
missing the email-verification and password-reset endpoints entirely, which are now listed.

`oauth_identity` raises one question this document does **not** settle: `app_user.password_hash` is
`NOT NULL`, but an SSO-only account has no password. Either it becomes nullable with a guard ensuring an
identity row exists, or every account must set a password. **[PROPOSED — confirm]** before FR-A6 is built.

**Deferred, documented, not built:** social sign-in (FR-A6) and payment checkout. The schema for both is in
place so it is stable when they are implemented; nothing writes to `oauth_identity` in v1.

**Not yet verified:** the migrations have **not been executed against a live database**. First `supabase db push` should be treated as the real test.

### 14.4 Found during frontend Phases 6–9

Implementation findings, recorded here because each one changes what another track must build or must not
assume.

| # | Finding | Consequence |
|---|---|---|
| 1 | **No endpoint switches the factor mid-challenge.** `POST /auth/2fa/resend` re-sends an email OTP to a user *already enrolled* in email OTP, but nothing sends a first OTP to a user enrolled in TOTP — so the prototype's "Email OTP" entry in the chooser has no request behind it | The chooser offers **backup code** as the only alternative factor, since enrolment has already handed those over, and an email-OTP challenge gets a **resend** control instead. **Muneeb** to confirm whether switching factor mid-challenge is intended at all; if it is, it needs a send endpoint |
| 2 | **Enrolment has no resend.** `2fa/resend` takes a **pending** token, not an `enrollment_token`, so a student whose enrolment OTP is delayed has no endpoint to call | The enrolment screen re-calls `POST /auth/2fa/enroll`, which by shape re-triggers the send. **Muneeb** to confirm that is safe and rate-limited, or to widen `2fa/resend` to accept an `enrollment_token` |
| 3 | **A `401` on `/auth/login` must not be retried after a refresh.** The generic 401→refresh→retry path fires a guaranteed-to-fail refresh on every mistyped password | Client gained a per-request `noRetry` flag (§3.10). No backend change |
| 4 | **`email/verify` is idempotent in practice but unspecified.** A verification link is commonly opened twice — a mail client prefetch, then the human | The client treats a second call returning `INVALID_TOKEN` as "already verified" only when it can confirm the state; otherwise it shows the invalid-link panel. **Muneeb** to confirm whether a spent token returns `INVALID_TOKEN` or succeeds idempotently |
| 5 | **Guardian status has no push channel.** The student's gate screen must discover that the parent confirmed | The client polls `GET /auth/guardian/status`, pausing while the tab is hidden. **Mujtaba** to confirm the polling interval is acceptable against the rate limiter |
| 6 | **`POST /auth/guardian/confirm` has no specified request body.** It is authenticated as the parent, but nothing says how the server learns WHICH pending link is being confirmed — a parent with two children cannot say | The client sends `{ invite_token }` from the email link, matching the rule that a token is always a body field. **Mujtaba** to confirm, or to key it off the parent's identity alone, in which case the field is dropped |

### 14.5 Found during frontend Phases 10–12

**The Content-Security-Policy shipped in Phase 1 broke the entire application, silently.** `script-src 'self'`
blocks the App Router's inline bootstrap scripts, which carry the React payload. React therefore never
hydrated: every page rendered as static HTML, no form accepted input and no button responded. It produced no
console output and every asset returned `200`, which is why it survived five phases unnoticed — component
tests all passed, because they render React directly and never see a CSP.

`script-src` now carries **`'unsafe-inline'`**, and that is a deliberate, recorded deviation from §6.11.
The correct fix is a per-request nonce; it cannot be used here, because a nonce must differ per response and
these routes are **prerendered per locale at build time**. Forcing them dynamic would trade the static
prerendering `prd.md` A11Y-2 depends on — a fast first paint on a mid-tier Android over Slow 3G — for a
directive that stops a subset of XSS payloads. `frame-ancestors`, `form-action`, `base-uri`, `connect-src`
and `img-src` are unchanged and still carry most of the value for an authentication surface.

**The lesson worth keeping:** a production build was never opened in a browser until Phase 12. Type checks,
lint, unit tests and `next build` all passed throughout while the shipped artefact was inert. `npm start` plus
one real interaction belongs in the definition of done, and is now in §9.5.

---

**Document Status:** Draft v0.3.7 — critically reviewed, awaiting user section-by-section review.
**Next Review:** on resolution of the [PROPOSED] items and user feedback.
**Downstream:** on acceptance, this TDD drives Epics → Stories → Tasks → Implementation.








