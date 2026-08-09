# Product Requirement Document

## EduBridge AI — A Secure, Agentic, Multilingual Learning Platform for Secondary & Higher-Secondary Students

**Version:** 0.3.5
**Status:** Draft — under section-by-section review
**Last Updated:** August 9, 2026
**Product Owner:** EduBridge AI Team (Group Leader: Yahya Mobeen)
**Supervisor:** Dr. Muhammad Arif Butt — Department of Data Science, FCIT, University of the Punjab
**Authors:** Osairum Ahmad Khan (BSDSF23A019), Muhammad Mujtaba (BSDSF23A026), Abdul Muneeb (BSDSF23A036), Yahya Mobeen (BSDSF23A039)
**Source of truth:** `EDUBRIDGE_AI_PROPOSAL.pdf` (FYP Proposal) · **Downstream:** `tdd.md` (Technical Design, derived from this PRD)

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-07-19 | EduBridge AI Team | Initial PRD draft derived from the approved FYP proposal and the agreed planning blueprint. Adopts supervisor PRD format; extended to engineering depth for TDD derivation. |
| 0.1.1 | 2026-07-19 | EduBridge AI Team | Added **TEL-5** endpoint access logging + admin daily-logs view; entity `ApiRequestLog`; RBAC + Admin-dashboard updates (kept in sync with TDD v0.1.1). |
| 0.3.5 | 2026-08-09 | EduBridge AI Team | **Consistency pass, driven by writing the User Stories & Epics deliverable.** Three capabilities that the product had promised but never specified gain requirements: **FR-A7** password reset (built and fully designed in `tdd.md`, yet no FR had ever covered it), **FR-A8** manage own account (granted to every role by the §4.2 matrix since v0.1.0, with no requirement and no endpoint behind it), and **FR-18** the English-language subject under a new **Epic C3** (one of four `content_strategy` values the router has dispatched on since v0.2.0). Three §4.2 cells that could not work are closed: a **parent can no longer create spaces, issue join codes or post announcements**, because the `guardian_link` write boundary makes the student-initiated invite the only route to a verified link — a join code produces no invite token. **§15 CL-2** loses "chat history" as a digest input; chat is owner-only and a teacher has no read path, so the digest carries no tutor-derived signal at all. **§15 CL-3** recasts "replay an avatar explanation" as a recommendation rather than a parent control. **§4.3 and §6.1** gain the **fail-closed rule** for an unknown class level, which had existed only in `tdd.md`. The **P0 Definition of Done** now includes second-factor enrolment and plan selection, both P0 and both previously missing, and the P0 scope list gains Epic C2. Record fixes: §12.2 retitled (it describes four strategies, not two), Epic C tiered P1 rather than P2, §2.3 and §29 aligned on O1's epics, and §19 reordered so I18N-4a precedes I18N-5 and the RTL mirroring rule sits with I18N-4 instead of inside the identifier rule. |
| 0.3.4 | 2026-08-02 | EduBridge AI Team | **Frontend build complete.** §19 gains **I18N-4a**: the RTL rule is now enforced by an automated sweep rather than by reviewer memory, because every supplied prototype is written with physical direction properties that look correct in English and silently break Urdu. No scope change. |
| 0.3.3 | 2026-08-02 | EduBridge AI Team | **Accessibility rules made testable** during frontend build: **A11Y-1a** (errors carried by icon + text + colour, and countdowns announced per minute rather than per second) and **A11Y-1b** (focus moves to a step's single field, and returns to it after a rejected code). No scope change; both make A11Y-1 checkable in review rather than aspirational. |
| 0.3.2 | 2026-08-02 | EduBridge AI Team | **Access is now paid** — new §2.6 defines a single tier (Rs. 999/month, PKR) with a **14-day trial and no free tier**, students only; onboarding gains the derived state **`plan_selection_pending`** after the parental gate, and it is **re-entrant** (a student returns to it when the trial lapses). **Parental-gate mechanism resolved to a student-initiated email invite** (§4.3, §6.1, §6.2), closing open decision 4. **Teachers no longer have tutor access** (§4.2) — aligns the matrix with `tdd.md` §3.2, which scoped `/api/tutor/ask` to students. **FR-A1** now captures `student_group` and `language_pref`; **FR-A5** (plan selection) and **FR-A6** (social sign-in, deferred) added. §19 records the RTL implementation rule; §26 flags minors as the subscriber of record. |
| 0.3.1 | 2026-08-01 | EduBridge AI Team | Login now returns **`200` with a `status` discriminator** instead of `401 TWO_FACTOR_REQUIRED`; a correct password is a success, not an error. `TWO_FACTOR_REQUIRED` and `TWO_FACTOR_ENROLLMENT_REQUIRED` removed from the error catalogue. |
| 0.3.0 | 2026-08-01 | EduBridge AI Team | **Two-factor authentication mandatory for all roles** — added **FR-A4** (enrolment + challenge) and **SEC-14** (TOTP primary, email-OTP fallback, hashed single-use backup codes, admin-assisted recovery). Data model gains `TwoFactorEnrollment` and `TwoFactorBackupCode`. NFR-2 records the usability trade-off and its mitigations. |
| 0.2.0 | 2026-08-01 | EduBridge AI Team | **Subject matrix expanded to 10 subjects** with per-class lists and **elective groups** (science/computer, pre-medical/pre-engineering/ICS). Two content branches replaced by **four content strategies**, adding **FR-17 religious-verbatim** (Quran Translation is retrieval-only). Database moved to **Supabase**; **Row Level Security** added as defense-in-depth (SEC-13). Data model updated (`subject_group`, `student_group`, `content_strategy`, `question_key`, `agent_component`). |

> **Reading note.** Priorities are tagged **P0 / P1 / P2** (see §23 Roadmap). Requirements use the IDs `FR-N` (functional), `SEC-N` (security), `NFR-N` (non-functional), and `US-x.x` (user stories). Items marked **[PROPOSED — confirm]** are open decisions to be resolved during review (consolidated in §2.5 and referenced inline).

---

## 1. Executive Summary

EduBridge AI is a curriculum-aligned, AI-powered learning platform for Pakistani students in **Classes 9–12** that bridges the gap between traditional classroom education and modern AI-based learning. Students today depend on textbooks, classroom teaching, and scattered online resources, while existing AI tutors are built for foreign curricula, assume English-first digital fluency, and are not aligned with Pakistani board structures, local languages, or how students naturally ask questions.

EduBridge AI closes this gap with a single platform that lets a student interact with a **curriculum-grounded AI tutor** through text and voice in **English, Urdu, and Roman-Urdu**, backed by visual learning aids and an avatar tutor. On top of the tutor sits a **classroom & collaboration layer** for teachers and parents, an **adaptive assessment and analytics** engine, a **self-updating curriculum pipeline**, and a cross-cutting **Secure Skills & MCP Layer** that validates, restricts, and monitors every agent skill and MCP server against current OWASP guidance for LLM and agentic applications.

The system is **agentic**: an LLM-based agent (Qwen) decomposes a request and calls skills/tools over the **Model Context Protocol (MCP)**, grounding answers on curriculum resources via retrieval-first generation. Because agentic systems inherit new supply-chain risks (prompt injection, unsafe tool execution, knowledge-base poisoning), security and insight are **built in rather than assumed**.

This PRD is an **engineering product requirements document**: it specifies personas, roles, functional and non-functional requirements, a domain data model, state machines, security requirements mapped to OWASP, measurable success metrics, and a prioritized roadmap — at a depth sufficient for the Technical Design Document (`tdd.md`) to be derived directly from it.

### 1.1 Key Value Propositions

- **Curriculum-exact tutoring** — grounded in official **PCTB** (Punjab) and **STBB** (Sindh) textbooks and curriculum documents, class-specific for Classes 9–12, not generic internet answers.
- **Truly multilingual** — understands short, informal queries and answers in **English, Urdu, and Roman-Urdu**; answers are *generated in the student's language* (grounded, not machine-translated after the fact).
- **Multimodal & guided** — retrieval-first visual aids plus a talking **avatar tutor** that explains out loud in Urdu and English.
- **Measured progress, not just scores** — per-SLO mastery (BKT), difficulty-calibrated items (IRT), past-paper frequency, and a single **exam-readiness** score with a ranked "study-next" plan.
- **Classroom at scale** — teachers run secure quizzes and receive automated weak-area reports across large cohorts; parents get read-only progress visibility.
- **Secure by design** — every skill/MCP server is vetted, least-privileged, sandboxed, and audited (**AgentSBOM**), mapped to OWASP LLM & Agentic guidance.
- **Locally deployable & low-cost** — hybrid model hosting (open/self-hosted where feasible, hosted APIs where needed) to protect student data and control cost.

---

## 2. Product Overview

### 2.1 Problem Statement

There is no learning platform that is, at the same time:

1. **Curriculum- and language-aligned** — aligned to the Punjab and Sindh board syllabi and able to teach local students in their own language, with visuals and speech;
2. **Securely agentic** — built as an agentic system whose skills and MCP servers are actually checked against the new agentic supply-chain threats; and
3. **Classroom-aware at scale** — able to give teachers real-time visibility into individual student performance when a single teacher manages 150+ students across sections, where manual monitoring is not feasible.

Today's AI tutors target foreign curricula and assume digital fluency; today's agentic apps add third-party skills and MCP servers without vetting (exposing users to malware, prompt injection, and data poisoning); and today's classrooms leave teachers with no practical way to track who is struggling with what. EduBridge AI is meant to be exactly this missing platform.

### 2.2 Solution & Vision

A secure, agentic, multimodal, multilingual learning companion for Pakistani students that combines curriculum-aligned tutoring with classroom-level quiz administration and performance analytics, in which every third-party skill and MCP server is checked, limited, and audited using current OWASP guidance.

A student asks in English, Urdu, or Roman-Urdu (typed or spoken); the agent grounds the answer on curriculum content through cross-lingual retrieval, generates the answer in the student's language, adds a retrieval-first visual aid, and can speak it through an avatar. Teachers and parents connect through class spaces to run secure quizzes and read automated weak-area reports. The knowledge base keeps itself current through a source-checked self-updating pipeline, and the Secure Skills & MCP Layer guards every step.

### 2.3 Objectives

The proposal defines **seven objectives**; this PRD carries all of them, prioritized across the roadmap (§23):

| # | Objective | Primary epic(s) | Tier |
|---|-----------|-----------------|------|
| O1 | Class-specific **Board Curriculum Chatbots** (Classes 9, 10, 11/FSc-I, 12/FSc-II) for NCP-aligned PCTB and STBB, loaded from official textbooks; understand short informal queries and adapt language to class level. | B, C, C2, C3 | P0 |
| O2 | **Adaptive quiz-evaluation engine** that scores attempts and adjusts difficulty/content by performance. | E | P1 |
| O3 | **Syllabus-coverage tracking** + auto-generated **weekly performance report**. | F | P1 |
| O4 | **Classroom space** where teachers enroll students, create/conduct subject-wise quizzes, and receive post-quiz collective weak-area reports. | G | P1 |
| O5 | **Retrieval-first multimodal layer** — retrieved or code-rendered visual aids + on-screen avatar tutor (Urdu/English, open-source TTS). | D | P0 |
| O6 | **Self-updating curriculum pipeline** that ingests newly released board syllabi and refreshes the KB after checking the source. | J | P2 |
| O7 | **Secure Skills & MCP Layer** — scans every skill/MCP server, least-privilege permissions, sandbox, runtime guards, and an AgentSBOM. | H, I | P1 (baseline safety in P0) |

### 2.4 Scope

**In scope (v1 documented target):**

- **Curriculum matrix:** Both boards — **PCTB (Punjab)** and **STBB (Sindh)** — **Classes 9–12**, across **10 subjects**: Mathematics, Physics, Chemistry, Biology, Computer Science, English, Urdu, Islamiat, Pakistan Studies, and Quran Translation. Subject lists differ per class and per **elective group** (§2.4.1). This yields **76 subject definitions** (2 boards × 38). *(Realized coverage per subject/board rolls out with the data-acquisition plan — §12; a constraint, not a scope cut.)*
- **Roles:** Student (primary), Teacher, Parent/Guardian, Admin (§3, §4).
- **Deployment:** Individual student self-serve (**primary**) **and** institutional/classroom use (secondary), both on the same platform.
- **Client:** Responsive **web** application (desktop + mobile browser).
- **Capabilities:** board curriculum chatbots; multilingual text+voice interaction; retrieval-first visual aids + avatar/voice; adaptive quizzes; syllabus-coverage tracking and reports; classroom spaces with secure quizzes; self-updating curriculum pipeline; Secure Skills & MCP Layer; rate-limiting & abuse control.

**Out of scope / Non-goals:**

- Training large foundation models from scratch (we use open models + retrieval + lightweight fine-tuning).
- Free-form diffusion **image generation** as a core path (kept as a **stretch**; visuals are retrieval-first + typed code-rendered).
- Direct student ↔ teacher **chat/messaging** (kept as a **stretch**; announcements are one-way in v1).
- **Boards beyond PCTB and STBB** (e.g., other provincial/federal boards) in v1.
- A **native mobile app** — v1 is responsive web only.
- Unrestricted autonomous multi-step agent behavior — the agent is confined to controlled, permissioned skills.

### 2.4.1 Subject Matrix & Elective Groups

Subject lists are **not uniform across classes**. A student belongs to an **elective group**, and the group determines which subjects apply.

| Level | Groups |
|---|---|
| **Matric (9–10)** | `science` (with Biology) · `computer` (with Computer Science) |
| **FSc (11–12)** | `pre_medical` (Biology, no Maths) · `pre_engineering` (Maths, no Biology) · `ics` (Maths + Computer Science) |

| Class | Group | Subjects |
|---|---|---|
| 9 & 10 | science | English, Urdu, Mathematics, Physics, Chemistry, **Biology**, Islamiat, Pakistan Studies, Quran Translation *(9)* |
| 9 & 10 | computer | English, Urdu, Mathematics, Physics, Chemistry, **Computer Science**, Islamiat, Pakistan Studies, Quran Translation *(9)* |
| 11 | pre_medical | English, Urdu, Physics, Chemistry, **Biology**, Islamiat, Quran Translation *(7)* |
| 11 | pre_engineering | English, Urdu, Physics, Chemistry, **Mathematics**, Islamiat, Quran Translation *(7)* |
| 11 | ics | English, Urdu, Physics, Chemistry, **Mathematics, Computer Science**, Islamiat, Quran Translation *(8)* |
| 12 | pre_medical | English, Urdu, Physics, Chemistry, **Biology**, Pakistan Studies, Quran Translation *(7)* |
| 12 | pre_engineering | English, Urdu, Physics, Chemistry, **Mathematics**, Pakistan Studies, Quran Translation *(7)* |
| 12 | ics | English, Urdu, Physics, Chemistry, **Mathematics, Computer Science**, Pakistan Studies, Quran Translation *(8)* |

**Rules:** Islamiat runs in Classes 9, 10, 11. Pakistan Studies runs in Classes 9, 10, 12. Quran Translation runs in all four years.

Group membership is a first-class attribute of the student profile, because **coverage % and exam-readiness must only be measured against subjects the student actually takes** (§13).

### 2.4.2 Content Strategies

Each subject declares **how the agent is permitted to answer it**. This replaces the proposal's original two-branch split and is enforced by the agent router, not by convention.

| Strategy | Subjects | Behaviour |
|---|---|---|
| `branch_a_english_source` | Mathematics, Physics, Chemistry, Biology, Computer Science, **Islamiat**, **Pakistan Studies** | One English-medium source of truth + cross-lingual retrieval; answer **generated in the student's language** with the board glossary. All of these are published in both English and Urdu medium with the same syllabus. |
| `branch_b_urdu_native` | Urdu | Structured Urdu notes corpus; retrieval-first, objective items word-for-word, productive items via controlled templates. |
| `english_language` | English | English-language subject — grammar, essay, and comprehension templates. |
| `religious_verbatim` | **Quran Translation** | **Retrieval only.** The board-approved text is returned word-for-word; the model may format but must **never compose or paraphrase**. If the text is absent from the knowledge base, the system says so rather than answering (see **FR-17**). |

### 2.5 Open Decisions (to confirm during review — each handled individually)

1. **Class 11 ICS subject list** — currently seeded as English, Urdu, Physics, Chemistry, Mathematics, Computer Science, Islamiat, Quran Translation (8 subjects). Traditional ICS often excludes Chemistry — confirm against the official scheme of studies. **[PROPOSED — confirm]**
2. **KPI thresholds** — adopt proposal NFR targets as KPIs vs. set specific numbers (§22). **[PROPOSED — confirm]**
3. **Institutional auth model** — institutions attach via classroom join-code only (no separate SSO/tenant) in v1 (§15). **[PROPOSED — confirm]**
4. **Parental-link enforcement & mechanism** — **RESOLVED (v0.3.2):** a **hard gate** for Classes 9–10, satisfied by a **student-initiated email invite**; the parent signs up and confirms out of band (§4.3, §6.1, §6.2). *Still open:* whether the student's class level is **self-declared or verified** at signup. **[PROPOSED — confirm]**
5. **Tiering split** — confirm P0/P1/P2 assignment (§23). **[PROPOSED — confirm]**
6. **Payment provider** — card plus EasyPaisa/JazzCash is the intent (§2.6); the acquirer is not chosen. Note that Stripe does not support Pakistani acquiring, so a card-only design is not shippable here. **[PROPOSED — confirm]**

---

### 2.6 Access & Monetisation

The platform is **paid**. There is **no free tier**: when a student's trial lapses and no subscription is
active, learning access stops.

| Aspect | Decision |
|---|---|
| Tiers | **One** — plan code `standard`, "EduBridge AI" |
| Price | **Rs. 999 / month**, currency **PKR** *(stored in minor units — 99900 paisa — so money is never a float)* |
| Trial | **14 days** from registration, granted automatically. The trial length is defined once, in the `subscription.trial_ends_at` schema default; no other component carries a copy of the number |
| Who pays | **Students only.** Teachers, parents and admins are never charged and never see plan selection |
| Payment methods | Card and **EasyPaisa / JazzCash** (provider open — §2.5 item 6) |

**MON-1 — Trial on registration.** Every student account is created with a `trialing` subscription. *AC:* a
student can use the product immediately after onboarding, without payment details.

**MON-2 — Fail closed.** The absence of a subscription record is **not** equivalent to "trialing". A student
with no record has no access. *AC:* a failed subscription insert can never silently grant indefinite free
access.

**MON-3 — Gate placement.** Plan selection is the **last** onboarding step, after the parental gate (§6.1).
A Class 9–10 student therefore has a verified guardian before any payment is discussed.

**MON-4 — Re-entrant.** Plan selection is **not** a one-way step. A student completes onboarding, becomes
active, uses the product for the trial period, and then returns to plan selection when the trial lapses.
*AC:* a live session whose trial expires mid-use is redirected on its next identity check, not left stranded
on a page it no longer has rights to.

> **Scope note.** Checkout is **not** part of the authentication/onboarding sprint. That sprint delivers the
> plan screen and the routing into it; payment capture is a separate card. See §26.5 for the minors'
> contracting question this raises.

---

## 3. Target Audience & Personas

### 3.1 Primary Users

**P-1 · Student (core consumer, primary user).**
- **Who:** Classes 9–12 students preparing for Punjab/Sindh board exams; often more comfortable in Urdu or Roman-Urdu than formal English; variable digital literacy; typically on a mobile browser, sometimes low-bandwidth.
- **Goals:** get curriculum-exact, class-specific help fast; understand steps and concepts; practice what is most likely to be examined; know how ready they are and what to revise next.
- **Pains:** foreign-curriculum tutors; English-only tools; no visibility into weak areas; generic answers not tied to their board/book.
- **Key needs:** short-query understanding, class/board-adaptive answers, EN/UR/Roman-Urdu, visuals + spoken explanations, quizzes, exam-readiness.

**P-2 · Teacher (primary user, institution-deployed).**
- **Who:** teachers managing large cohorts (150+ students across sections); subject specialists.
- **Goals:** create/run subject-wise quizzes; see collective and individual weak areas without manual tracking; get a weekly class digest.
- **Pains:** no practical way to track performance at scale; generic LMS tools don't do curriculum-aligned weak-area analytics.
- **Key needs:** minimal-friction quiz creation, secure delivery, subject-scoped reports (least-privilege).

### 3.2 Secondary Users

**P-3 · Parent/Guardian.**
- **Who:** parents of students, especially of younger (Class 9–10) minors.
- **Goals:** see their child's progress and weak areas; get a short, curriculum-grounded plan for how to help.
- **Key needs:** all-subject **read-only** visibility for their linked child; a how-to-help guide. **Required** for Class 9–10 students; optional for 11–12 (§4.3).

**P-4 · Admin (platform/institution operator).**
- **Who:** platform operators and institutional administrators.
- **Goals:** provision access; keep curriculum current (auto-update); review platform security posture (AgentSBOM, vetting results); manage abuse controls.
- **Key needs:** provisioning, curriculum/pipeline management, security & audit review, rate-limit/quota configuration.

**P-5 · Educational institution (primary customer, deployment context).**
- Schools/colleges offering secondary & higher-secondary education (~25k+ institutions) that deploy the platform for their teachers, students, and parents. Institutions attach through the classroom layer (§15).

### 3.3 Market Context (from proposal)

- **Institutions:** ~25k+ offering secondary/higher-secondary education. **Students:** ~2–3 million enroll for board examinations annually (the main target). Teachers and parents are connected through the platform.

---

## 4. Roles & RBAC Permissions Matrix

### 4.1 Roles

`STUDENT` (primary) · `TEACHER` (subject-scoped) · `PARENT` (read-only, linked child) · `ADMIN` (platform/curriculum/security). Access is enforced by **role-based access control (RBAC)** with **least-privilege** applied at the human layer — the same principle applied to skills/MCP servers (§16).

### 4.2 Permissions Matrix

Legend: ✅ allowed · 🔵 read-only · ⛔ not allowed · *scope notes inline*.

| Capability | Student | Teacher | Parent | Admin |
|---|---|---|---|---|
| Register / manage own account | ✅ (self-serve) | ✅ | ✅ | ✅ |
| Enrol / manage own second factor (2FA) | ✅ (required) | ✅ (required) | ✅ (required) | ✅ (required) |
| Reset another user's 2FA (identity-verified, audited) | ⛔ | ⛔ | ⛔ | ✅ |
| Use tutor chatbot (ask, voice, visuals, avatar) | ✅ | ⛔ *(see note)* | ⛔ | ⛔ |
| View own progress / coverage / exam-readiness | ✅ (own) | — | 🔵 (linked child, all subjects) | ⛔ |
| Create / edit class space | ⛔ | ✅ | ⛔ *(see note)* | ✅ |
| Enroll students / issue join codes | ⛔ | ✅ (own space) | ⛔ *(see note)* | ✅ |
| Create & run quizzes | ⛔ | ✅ (**own subject only**) | ⛔ | ✅ |
| View quiz/class reports | 🔵 (own results) | 🔵 (**own subject**, collective + individual) | 🔵 (linked child, all subjects) | 🔵 (aggregate) |
| View a student's chat content | 🔵 (own) | ⛔ | ⛔ | ⛔ (audit metadata only) |
| Manage curriculum KB / run auto-update | ⛔ | ⛔ | ⛔ | ✅ |
| Review security (vetting, AgentSBOM), set rate limits/quotas | ⛔ | ⛔ | ⛔ | ✅ |
| View daily endpoint access logs (traffic, status codes, messages) | ⛔ | ⛔ | ⛔ | ✅ |
| Post announcements to a space | ⛔ | ✅ (own space) | ⛔ *(see note)* | ✅ |

> **Note on teacher tutor access (changed in v0.3.2).** Through v0.3.1 this cell read *"✅ (own testing)"*,
> which contradicted `tdd.md` §3.2, where `POST /api/tutor/ask` has always been scoped to
> **Student (gate-verified)**. The TDD is authoritative: the tutor is **student-only**. This keeps the
> guardian-gate dependency a purely student-shaped check and keeps tutor usage out of teacher analytics.
> If teachers are later given a way to evaluate the tutor, it should be a separate, quota-limited endpoint
> rather than a widening of this one.

> **Note on parent spaces and join codes (changed in v0.3.5).** Through v0.3.4 these three cells granted a
> parent a "guardian space" with its own join code, as a second way to link to a child. That path can no
> longer work: the `guardian_link` write boundary added in `tdd.md` v0.3.5 makes `verified` reachable
> **only** through `app.confirm_guardian_link`, which demands an unexpired one-time invite token — and a
> join code never produces one. The **student-initiated email invite is the sole route** to a verified
> link (§4.3). Parents therefore create no spaces, issue no join codes and post no announcements; their
> visibility comes from the guardian link alone.

**Cross-cutting rules:**
- **The UI must not offer what the matrix forbids.** Navigation and controls are derived per role from this
  matrix — a role never renders a control it cannot use, even disabled. This is a requirement, not a
  presentation preference: a parent dashboard that shows a "replay this tutor session" button advertises a
  capability the matrix denies, and a shared component tree makes that failure easy to introduce by copying.
- **Consent by joining** — a **teacher** sees a student only after the student joins their space via a revocable **join code**. The student can see who can view them and can **leave any space at any time**. A **parent's** visibility comes from a verified guardian link (§4.3), not from a space.
- **Read-only viewers** — teachers/parents can see progress but can never chat as the student or change the student's settings.
- **Subject-scoped teacher** — a teacher declares the subject they teach; their reports are limited to that subject only (least-privilege).
- **Parent all-subject read-only** — a linked parent sees an all-subject report for their child plus a how-to-help plan.

### 4.3 Parental-Consent Gate (class-based)

To protect younger minors, parental linkage is **required by class level** for individual (self-serve) students:

| Student class | Parent/guardian link | Effect |
|---|---|---|
| **Class 9–10** | **Mandatory** | The student must have a **signed-up, linked, verified** parent/guardian to use the app; the parent can view the student's progress. Enforced at onboarding as a **hard gate** — no grace period (§6.1). |
| **Class 11–12** | **Optional** | Parent linkage is **offered** but not required; the student can use the app without it, and the gate is never displayed to them. |
| **Class level unknown** | **Mandatory** | **Fails closed** — the student is gated exactly as a Class 9–10 student is. See below. |

**Mechanism (resolved in v0.3.2).** The link is created by a **student-initiated email invite**: the student
enters a parent's email address, the parent receives an invite, **signs up**, and confirms the link from
their own account. Only then does the link become `verified`.

The direction and the channel both matter:

- **The signal must be out of band.** Verification happens in a mailbox the student does not control. A code
  the student types in — from any source — is not out of band, because everything it touches passes through
  the minor being protected.
- **A student must not be able to satisfy their own gate.** The parent account is distinct and separately
  authenticated, backed by the `CHECK (parent_id <> student_id)` constraint and a parent-role check in the
  service layer.

**The gate fails closed on an unknown class level (added in v0.3.5).** A student whose class level cannot
be read is **gated**, not waved through. Under Row Level Security an unreadable `student_profile` row is
indistinguishable from an absent one, and the two failure modes are not symmetric: gating an eighteen-year-old
in error costs them an invite they did not need, while releasing a fourteen-year-old in error serves a minor
without consent. `onboarding_state` must report `guardian_link_pending` whenever the gate holds, so the
student lands on a screen that can resolve it rather than on a dead end.

This gate reinforces the platform's minors'-data and consent posture (§26) and is keyed on the student's class level *(self-declared vs. verified at signup — **[PROPOSED — confirm]**)*.

---

## 5. System Architecture (product-level)

EduBridge AI uses a **layered, agentic** design. This section defines component responsibilities at the product level; the deep technical design (interfaces, schemas, deployment topology) is produced in `tdd.md` (§30 map).

**5.1 Presentation Layer — React / Next.js / Tailwind (responsive web).**
Authentication & access; role dashboards (student, teacher, parent, admin); the tutor chat UI (text + voice input, EN/UR/Roman-Urdu, RTL for Urdu); retrieval-first visual-aid renderer (sandboxed); avatar + audio player; classroom & quiz UIs; reports.

**5.2 Application Layer — Python / FastAPI.**
- **Agent orchestrator** — the LLM agent (Qwen) with **LangGraph**, decomposes a request and routes to skills/MCP tools.
- **Skill router** — dispatches to self-created skills and audited third-party skills/MCP.
- **Retrieval service** — cross-lingual retrieval (**BGE-M3**) + reranking (**BGE-reranker-v2-m3**) over the English-medium KB; Urdu-corpus retrieval for Branch B.
- **Classroom & quiz services** — spaces, enrollment, quiz build/deliver/grade, reports.
- **API gateway / rate limiting** — Redis token-bucket per user/IP (§17).
- **MCP clients** — connect to audited MCP servers.

**5.3 Agent Skills & MCP.**
- **Self-created skills:** Curriculum Retriever, Syllabus Updater, Adaptive-Language, Visual Renderer.
- **Audited third-party skills / MCP servers:** TTS/Avatar (Fish Audio S2 Pro), STT (Whisper), OCR, Translation, Vector DB, Web Search, document export.
- **Public MCP registry** — external servers are admitted only through the Secure Skills & MCP Layer (§16).

**5.4 Data Layer.**
**Supabase (managed PostgreSQL)** is the OLTP source of truth for users, roles, progress, quizzes, and logs, with **Row Level Security** enforced as defense-in-depth (§16, SEC-13). A dedicated **vector DB** (FAISS/ChromaDB) holds embeddings; a separate **star-schema analytics layer** serves reports; **Redis** provides cache + rate-limit buckets; object storage holds KB documents and indexed textbook figures. KB is **versioned by board + curriculum year** (§12).

> Authentication is **application-managed** — FastAPI issues its own JWTs and hashes passwords with argon2id. Supabase Auth is deliberately not used, so Supabase acts purely as the database platform.

**5.5 Cross-cutting — Secure Skills & MCP Layer (OWASP-mapped).**
Runs across all layers: vetting scanner, permission manifests, least-privilege enforcement, sandboxing (CSP/container), runtime guardrails (input/output), and **AgentSBOM** generation (§16).

**5.6 Platform / DevOps.**
CI/CD via **GitHub Actions**; containerized with **Docker**; the **self-updating curriculum pipeline** (source-checked) refreshes the KB (§12, §6.6).

**5.7 Runtime model registry (per stage).** See §11 (Table 11.1).

---

## 6. User Journeys & Flows

### 6.1 Student onboarding + parental-consent gate

Onboarding progress is carried by a single **derived** value, `onboarding_state`, returned from the identity
endpoint. It is computed from email verification, two-factor status, guardian link and subscription — it is
not stored as a column, and clients **route on this field alone** rather than inferring progress from a
combination of flags.

```
register ──► email_verification_pending
                    │ verifies email
                    ▼
             two_factor_enrollment_pending
                    │ enrols + confirms a factor
                    ▼
             guardian_link_pending          [Classes 9–10 only]
                    │ parent signs up and confirms
                    ▼
                  active   ◄─── 14-day trial running
                    │ trial lapses with no subscription
                    ▼
             plan_selection_pending         [students only]
                    │ subscribes
                    └──────► active
```

1. Student signs up (self-serve) with minimal PII; selects **board**, **class (9–12)**, **elective group**, **medium**, and **interface language**.
1a. **Email verification** — the student confirms their address before proceeding.
1b. **Two-factor enrolment (mandatory, FR-A4)** — the student chooses TOTP or email-OTP **as equally weighted options**, confirms one challenge, and saves the 10 backup codes shown once. Full access is withheld until this completes.
2. **If Class 9–10, or if the class level cannot be read:** the student must link a parent/guardian. The student enters a parent's **email address**; the parent signs up and confirms, and the link becomes **verified** (§4.3). *Full tutor access is gated until then — a hard gate.* **An unknown class level fails closed and is gated** — see §4.3.
3. **If Class 11–12:** parental linkage is **offered but optional**; the student proceeds directly. A Class 11–12 student is **never** shown the gate, and may still choose to invite a parent later.
4. **Plan selection (FR-A5)** — reached only once the 14-day trial lapses without an active subscription (§2.6). New students pass straight through to step 5 and meet this later.
5. Student lands on the student dashboard (progress, recent chats, avatar entry point).

> **The chain is not one-way.** Step 4 is re-entrant: a student who is `active` returns to
> `plan_selection_pending` when the trial expires. Any client that evaluates `onboarding_state` once on
> entry and then trusts it will strand such a user (§2.6 MON-4).

### 6.2 Parent onboarding / linking

1. Parent receives an invite email, triggered by their child entering the parent's address (§4.3).
2. Parent **signs up** for their own account, then confirms the link from it. Confirmation is an
   authenticated action: the link is only `verified` once a distinct, separately authenticated parent
   account has accepted it.
3. Parent is linked to the child (all-subject **read-only**) and the child's gate clears.
4. Parent dashboard shows the child's coverage, weak areas, and a how-to-help plan (§15) — and **no tutor,
   chat-replay or write control of any kind** (§4.2).

### 6.3 Runtime tutor flow (text or voice in, voice out) — 9 steps

1. **Input** — student types or speaks a question in Urdu, English, or Roman-Urdu.
2. **STT & intent** — if spoken, **Whisper** transcribes; **Qwen** detects language and parses the short query into subject, class, board, task.
3. **Input guardrail** — **Prompt Guard 2 / Llama Guard 3** check input; **Redis** rate limiter blocks abusive rates (LLM10); the Secure Skills & MCP Layer checks any tool call.
4. **Routing** — the subject's `content_strategy` (§2.4.2) selects the path: `branch_a_english_source` uses cross-lingual retrieval (**BGE-M3**) over the English KB, reranked (**BGE-reranker-v2-m3**); `branch_b_urdu_native` retrieves from the Urdu notes corpus; `english_language` uses the English corpus + exam templates; `religious_verbatim` retrieves only, with generation disabled.
5. **Generation** — **Qwen** writes the answer grounded in retrieved content, in the student's language (generate-in-Urdu with glossary for A; fill exam template for B).
6. **Visual decision** — try to retrieve the indexed textbook figure (indexed offline by **Qwen2.5-VL**); else render a typed code-based visual (Mermaid / KaTeX / chart-JSON / function-plot).
7. **Output guardrail** — **Llama Guard 3** checks output; the visual is shown as typed, **sandboxed** content (LLM05).
8. **Voice synthesis** — **Fish Audio S2 Pro** speaks the answer in EN/UR with the cloned tutor voice.
9. **Avatar** — **MuseTalk v1.5** lip-syncs the avatar to the audio; the student receives text + visual + talking avatar.

### 6.4 Quiz lifecycle

Teacher (or agent-draft + teacher approval) builds a quiz → publishes to a space with a time window → students attempt (shuffled items, one attempt, server-side keys, auto-submit on timeout) → auto-grading → teacher receives per-student scores + class collective weak areas; student sees own result; mastery/coverage updated (§13). State machine in §10.

### 6.5 Classroom enrollment / consent (join code)

Teacher/parent creates a space and shares a unique, revocable **join code** → student enters the code (the act of joining is consent) → viewer becomes read-only over the student → student can leave anytime (§15).

### 6.6 Self-update ingestion (source-checked)

New board syllabus/textbook detected → **provenance/source check** (authenticity/signature) → on pass, parse/index into the KB with a new **board+year version** → KB integrity verified → available to retrieval; on fail, quarantined and flagged to Admin (§12, O6). State machine in §10.

### 6.7 Skill/MCP vetting

A new/updated skill or MCP server is submitted → static scan + claim-vs-actual capability check → permission **manifest** assigned (least-privilege) → sandboxed → admitted with an **AgentSBOM** entry; runtime guardrails monitor each call; violations are blocked and logged (§16). State machine in §10.

---

## 7. Functional Requirements

Requirements are grouped by **Epic** (A–K). Each carries the proposal's `FR-ID`, the user-story-form requirement and acceptance criteria (verbatim from the proposal), plus **tier**, **primary role**, **dependencies**, and **edge/failure** notes added for engineering. Epics **A** and **K** have no proposal FR-ID (derived from proposal §1.5.1) and are marked *derived*.

### Epic A — Authentication, Roles & RBAC *(derived; P0)*
- **FR-A1 (P0):** Self-serve **registration & login** (JWT) for student, teacher and parent roles. Student registration captures **board**, **class level**, **elective group**, **medium** and **interface language**. *AC:* account created and role assigned; **no session is issued at registration** — the account enters `email_verification_pending` (§6.1) and a session is only granted once the second factor is satisfied. The offered elective groups are **derived from the chosen class** and an invalid class/group pair is rejected, so `science` cannot survive a switch from Class 9 to Class 11. *Deps:* §2.4.1, §4. *Edge:* duplicate email; weak password; invalid class/group pair; unverified email.
- **FR-A2 (P0):** **Role-based access control** for student/teacher/parent/admin. *AC:* each capability enforced per §4.2 matrix. *Edge:* privilege-escalation attempt → denied + audited.
- **FR-A4 (P0):** **Two-factor authentication — mandatory for every role.** *As any user, I want a second authentication factor, so that a stolen password alone cannot expose a student's account or data.* **AC:** after email verification, the user must enrol a second factor before gaining full access; login becomes two-step (password → factor challenge); a valid challenge is required for every new session. **Methods:** **TOTP** (authenticator app) is primary; **email-OTP** is offered for users without a smartphone; **10 single-use backup codes** are issued at enrolment and shown exactly once. *Role:* all. *Deps:* email verification, SEC-14. *Edge:* lost device → backup code; lost device *and* codes → admin-assisted recovery with identity verification (audited); repeated failures → temporary lock, not permanent lockout.

  > **Accessibility note.** Mandatory 2FA is in tension with **NFR-2** ("usable by students new to digital tools, without training"). Many Class 9–10 students share a device or have no smartphone. The email-OTP method and backup codes exist specifically to keep that cohort from being locked out; enrolment UX must therefore present email-OTP as an equal option, not a fallback buried behind TOTP.

- **FR-A3 (P0):** **Class-based parental-consent gate** — Class 9–10 require a verified parent link before full access; 11–12 optional. The link is created by a **student-initiated email invite**; the parent signs up and confirms from their own account (§4.3). *AC:* a 9–10 student is blocked from full tutor use until the parent is verified; a **Class 11–12 student is never shown the gate**; a student cannot satisfy their own gate. *Deps:* §4.3, §6.1. *Edge:* parent never confirms → student remains gated, **no grace period**; student enters their own address → rejected; invite resendable and the address changeable.

- **FR-A5 (P0):** **Plan selection.** *As a student whose trial has ended, I want to see what the subscription costs and choose it, so that I can carry on studying.* **AC:** a student whose 14-day trial has lapsed without an active subscription is routed to plan selection and cannot reach learning features until a subscription is active; teachers, parents and admins are never routed there; a student **already active** whose trial lapses mid-session is redirected on their next identity check rather than left on a page they no longer have rights to. *Role:* Student. *Deps:* §2.6, §6.1. *Edge:* missing subscription record → treated as no access, never as a trial (MON-2); payment failure → remains gated with a retry path.

- **FR-A6 (P2, deferred — not built in v1):** **Social sign-in** with Google and Microsoft as an alternative to email/password. *AC:* an external identity maps to exactly one local account; a user links a given provider at most once; email/password remains available. *Role:* all. *Deps:* §16. *Edge:* provider email already registered → link rather than duplicate; provider-only account has no password to reset.

  > **This is consumer social login, not institutional SSO.** It does not change §15 CL-6 or §2.5 item 3,
  > which concern multi-tenant/institutional identity and remain out of scope for v1. The supporting table
  > (`oauth_identity`) is in the schema so it is stable when the feature is built; nothing writes to it yet.

- **FR-A7 (P0):** **Self-service password reset.** *As a user who has forgotten my password, I want a secure self-service way to set a new one, so that I can regain access without contacting anyone.* *AC:* the request response is identical in body, status and timing whether or not the address exists; a single-use, time-limited link is issued; completing a reset never bypasses the second factor. *Role:* all. *Deps:* SEC-14. *Edge:* a spent token and a lapsed token are distinguishable, so a resend is offered only for the latter. *(Added in v0.3.5 — the endpoints, error semantics and constant-time behaviour were fully specified in `tdd.md` §3.1/§7.3 and built, but no functional requirement had ever covered them.)*

- **FR-A8 (P1):** **Manage own account.** *As any user, I want to change my password, my language and my details from inside my account, so that I am not forced through a reset email to change something I already know.* *AC:* a signed-in user can change their password after re-authenticating with the current one; the **stored language preference** can be changed and governs the language of subsequent outgoing email; own second-factor **status** is visible but the secret never is; everything is scoped to the acting user. *Role:* all. *Deps:* §4.2. *Edge:* the stored language preference and the interface locale are distinct settings and must be presented as such. *(Added in v0.3.5 — §4.2 has granted this to every role since v0.1.0, but no requirement described it and `tdd.md` routed nothing for it.)*

### Epic B — Board Curriculum Chatbot *(P0)*
- **FR-1 (P0):** *As a Class-9 student, I want to type "math 9 chp 4 ex 4.5 q 3" and get the exact question with a step-by-step solution.* **AC:** right question found; step-wise solution; option to explain a step. *Role:* Student. *Deps:* KB (§12), retrieval (§11). *Edge:* question not in KB → graceful "not found / closest match"; ambiguous reference → clarify.
- **FR-2 (P0):** *As an FSc student, I want answers in more technical English so they match my class level.* **AC:** vocabulary adapts to the class level. *Edge:* class mismatch → adapt to enrolled class.
- **FR-7 (P0):** *As an Urdu-medium student, I want answers in Urdu that use my textbook's exact terms.* **AC:** generate-in-Urdu; board-aligned terminology glossary applied. *Deps:* glossary (§12). *Edge:* missing glossary term → flag + fallback term.

### Epic C — Urdu-Lazmi Subject *(P0 partial → P1 full)*
- **FR-8 (P0):** *As a student, I want the tashreeh of a couplet in the standard exam format.* **AC:** retrieved/structured template: intro → meaning → tashreeh → devices → central idea. *Deps:* Urdu notes corpus (§12). *Edge:* couplet not in corpus → no fabrication; return closest + note.
- **FR-9 (P1):** *As a student, I want an essay or letter of the right length and structure.* **AC:** length is controlled; intro → body → conclusion. *Edge:* topic outside corpus → template scaffold only, flagged.

### Epic C2 — Religious Content (Quran Translation) *(P0)*
- **FR-17 (P0):** *As a student, I want the Quran translation exactly as it appears in my board-approved textbook, so that what I study and reproduce in the exam is authentic.* **AC:** the stored board-approved text is returned **word-for-word**; the model may format or locate a verse but **generation/paraphrase is disabled** for this subject; a retrieval miss returns an explicit "not found in the knowledge base" rather than an answer; the response cites the source reference. *Role:* Student. *Deps:* §12, §2.4.2. *Edge:* partial/ambiguous verse reference → ask to clarify, never guess. *Rationale:* an invented or paraphrased Quranic translation is an ethical failure, not merely an accuracy one — this subject therefore has stricter handling than any other.

### Epic C3 — English-Language Subject *(P1)*
- **FR-18 (P1):** *As an English-subject student, I want grammar, comprehension and composition answered in my examination's format, so that I practise the form the paper actually asks for.* **AC:** items are answered from the structured English corpus against fixed exam formats, mirroring the Urdu treatment but in English; fixed and objective items are returned from the corpus rather than freely composed; composition items (essay, letter, application) are built from a template scaffold with controlled length; comprehension is answered against the retrieved passage. *Role:* Student. *Deps:* §2.4.2 (`english_language`), §12.2. *Edge:* topic outside the corpus → scaffold only, flagged. *(Added in v0.3.5 — `english_language` has been one of four `content_strategy` values since v0.2.0 and the agent router dispatches on it, but no functional requirement had ever covered it.)*

### Epic D — Multimodal: Visual Aids + Avatar/Voice *(P0)*
- **FR-5 (P0):** *As a student, I want the avatar to explain a topic out loud in my language so it feels guided.* **AC:** avatar with Fish S2 Pro TTS in Urdu/English; MuseTalk lip-sync. *Edge:* Urdu TTS quality low → ur-PK/local Urdu TTS fallback (§20).
- **FR-6 (P0):** *As a student, I want a relevant diagram or graph, taken from my textbook if there is one, otherwise drawn, so I can understand it visually.* **AC:** retrieval-first; safe code-rendered fallback; typed/sandboxed output (LLM05). *Edge:* no figure + render fails → curated image → text (§20).

### Epic E — Adaptive Assessment & Quizzes *(P1)*
- **FR-3 (P1):** *As a student, I want the quiz to adjust its difficulty based on how I'm performing, so it matches my level.* **AC:** difficulty/content adapts after each attempt; score recorded per attempt. *Deps:* IRT/BKT (§13). *Edge:* too few items at a difficulty → widen pool.
- **FR-15 (P1):** *As a student, I want quizzes built from the most frequent past-paper topics (last 5 years) so I practise what is most likely to be examined.* **AC:** questions drawn from high-frequency SLO clusters; filtered to the current syllabus. *Deps:* past-paper mining (§13). *Edge:* SLO not in current syllabus → excluded.

### Epic F — Progress, Coverage & Exam-Readiness Reports *(P1)*
- **FR-4 (P1):** *As a student, I want to see how much of my syllabus I've covered and get a weekly performance report.* **AC:** coverage % computed per subject; report auto-generated weekly. *Edge:* sparse data → low-confidence flag.
- **FR-16 (P1):** *As a student, I want a single exam-readiness score and a ranked "study next" list so I know where I stand and what to revise.* **AC:** per-SLO mastery (BKT); exam-readiness = mastery × frequency; list ranked by likely mark gain. *Deps:* §13.

### Epic G — Classroom & Spaces *(P1)*
- **FR-10 (P1):** *As a teacher, I want to enroll students into a class and create subject-wise quizzes through the app.* **AC:** roster created; quiz builder supports subject/topic tagging. *Deps:* spaces (§15). *Edge:* revoked join code; student leaves space.
- **FR-11 (P1):** *As a teacher, I want a report after each quiz showing the class's collective weak areas, not just individual scores.* **AC:** weak topics ranked by frequency of incorrect answers; collective and individual views shown. *Scope:* subject-scoped to the teacher.

### Epic H — Secure Skills & MCP Layer *(P1; baseline in P0)*
- **FR-13 (P1):** *As a security reviewer, I want every skill/MCP server scanned before use so malicious or over-privileged ones are blocked.* **AC:** claim-vs-actual mismatch flagged; AgentSBOM produced. *Deps:* §16. *Edge:* mismatch → block + quarantine + alert. *(Baseline input/output guardrails + sandboxed visuals ship in P0.)*

### Epic I — Platform Rate-Limiting & Abuse Control *(P1; baseline in P0)*
- **FR-14 (P0 baseline / P1 full):** *As the platform operator, I want per-user/IP rate limits on model calls so abuse and denial-of-service are prevented.* **AC:** Redis token-bucket limiter; requests over the limit get HTTP 429; quotas configurable. *Deps:* §17.

### Epic J — Self-Updating Curriculum Pipeline *(P2)*
- **FR-12 (P2):** *As an admin, I want new syllabi pulled in automatically so the content stays current.* **AC:** new source used only after its provenance is checked. *Deps:* §12, §6.6. *Edge:* provenance fail → quarantine + flag; never auto-ingest unverified.

### Epic K — Dashboards *(derived; per-role, P0→P1)*
- **FR-K1:** Role dashboards — Student (P0): progress, recent chats, avatar entry. Teacher (P1): spaces, quizzes, reports. Parent (P1): child progress + how-to-help. Admin (P1): provisioning, curriculum, security/AgentSBOM, quotas, **daily endpoint access logs (TEL-5)**. *AC:* each role sees only its permitted data (§4.2).

---

## 8. User Stories & Acceptance Criteria (Given/When/Then)

Each story carries its `US-x.x` id, source `FR`, tier, and testable Given/When/Then (GWT) criteria including at least one failure/edge path.

### Epic 1 — Account, Roles & Consent

**US-1.1 (FR-A1, P0) — Student self-serve signup.**
- **Given** a new student on the signup page, **when** they submit a unique email, password, board, class (9–12), elective group, medium and interface language, **then** an account is created and they are asked to verify their email. **No session is issued yet** — access begins only after email verification and second-factor enrolment (§6.1).
- **Given** an email already in use, **when** they submit, **then** signup is rejected with a clear message and no account is created.
- **Given** a student who chose Class 9 and the `science` group, **when** they change the class to 11, **then** the group selection is cleared and only Class-11 groups are offered, so an invalid class/group pair cannot be submitted.
- **Given** the reference data has not loaded, **when** the student reaches the academic step, **then** the group options are shown as unavailable rather than guessed at by the client.

**US-1.2 (FR-A3, P0) — Class 9–10 parental-consent gate.**
- **Given** a Class-9 or Class-10 student without a verified parent link, **when** they try to use the tutor, **then** access is gated and they are prompted to enter a parent's **email address**.
- **Given** the parent signs up and confirms the link from their own account, **when** the student returns, **then** full tutor access is granted.
- **Given** a Class-11/12 student, **when** they sign up, **then** they get full access without a required parent link, and the gate is **never** displayed to them.
- **Given** a student who enters **their own** email address as the parent's, **when** they submit, **then** the invite is rejected — a student cannot satisfy their own gate.

**US-1.4 (FR-A5, P0) — Trial expiry and plan selection.**
- **Given** a student whose 14-day trial has lapsed with no active subscription, **when** they sign in, **then** they are routed to plan selection and cannot reach learning features until a subscription is active.
- **Given** a student who is **already signed in and active**, **when** their trial lapses mid-session, **then** the next identity check redirects them to plan selection rather than leaving them on a page they no longer have rights to.
- **Given** a teacher or a parent, **when** they sign in, **then** plan selection is never shown — only students are charged.
- **Given** a student account with **no** subscription record at all, **when** access is evaluated, **then** it is treated as no access, never as an open-ended trial.

**US-1.3 (FR-A2, P0) — RBAC enforcement.**
- **Given** a teacher scoped to "Physics", **when** they open reports, **then** only Physics data for their space is shown; **when** they request another subject's data, **then** it is denied and the attempt is audited.
- **Given** a parent linked to a child, **when** they open the child's page, **then** all-subject data is **read-only**; **when** they try to chat as the student or change settings, **then** it is not permitted.

### Epic 2 — Board Curriculum Chatbot

**US-2.1 (FR-1, P0) — Exact question + step-by-step.**
- **Given** a Class-9 student types `math 9 chp 4 ex 4.5 q 3`, **when** the query is processed, **then** the exact question is located and a step-wise solution is returned with an "explain this step" option.
- **Given** the referenced item is not in the KB, **when** processed, **then** the tutor states it cannot find that exact item and offers the closest match rather than fabricating one.

**US-2.2 (FR-2, P0) — Class-adaptive language.**
- **Given** an FSc (Class 11/12) student, **when** they ask a concept question, **then** the answer uses more technical English appropriate to their class level; **given** a Class-9 student, **then** the same concept is explained more simply.

**US-2.3 (FR-7, P0) — Generate-in-Urdu with glossary.**
- **Given** an Urdu-medium student asks in Urdu/Roman-Urdu, **when** answered, **then** the response is written directly in Urdu (not post-translated) using the board-aligned terminology glossary for that board/subject.
- **Given** a term missing from the glossary, **when** answered, **then** the gap is flagged and a safe fallback term is used.

### Epic 3 — Urdu-Lazmi Subject

**US-3.1 (FR-8, P0) — Couplet tashreeh in exam format.**
- **Given** a student requests the tashreeh of a couplet in the corpus, **when** answered, **then** the structured template is returned (intro → meaning → tashreeh → devices → central idea).
- **Given** the couplet is not in the corpus, **then** no tashreeh is fabricated; the closest match is offered with a note.

**US-3.2 (FR-9, P1) — Essay/letter of correct length & structure.**
- **Given** a student requests an essay/letter on a topic, **when** produced, **then** it follows intro → body → conclusion with controlled length; productive text is built from a template scaffold.

### Epic 4 — Multimodal (Visual Aids + Avatar/Voice)

**US-4.1 (FR-6, P0) — Retrieval-first visual aid.**
- **Given** a concept with an indexed textbook figure, **when** a visual is requested, **then** the textbook figure is shown; **given** none exists, **then** a typed code-rendered visual (Mermaid/KaTeX/chart-JSON/function-plot) is drawn.
- **Given** rendering fails, **then** the system falls back to a curated image and finally to text; **all** model-written visual code is rendered sandboxed (iframe + CSP + DOMPurify).

**US-4.2 (FR-5, P0) — Avatar explains out loud.**
- **Given** a student asks for a spoken explanation, **when** produced, **then** the avatar speaks the answer in the student's language (Fish S2 Pro TTS) with MuseTalk lip-sync.
- **Given** Urdu TTS quality is inadequate on validation, **then** the ur-PK/local Urdu TTS fallback is used.

### Epic 5 — Adaptive Assessment

**US-5.1 (FR-3, P1) — Adaptive difficulty.**
- **Given** a student answering a quiz, **when** they get items right/wrong, **then** subsequent item difficulty/content adapts and each attempt's score is recorded.

**US-5.2 (FR-15, P1) — Past-paper frequency quizzes.**
- **Given** a subject/chapter, **when** a quiz is generated, **then** items are drawn from high-frequency SLO clusters (last 5 years) filtered to the current syllabus; out-of-syllabus SLOs are excluded.

### Epic 6 — Progress, Coverage & Exam-Readiness

**US-6.1 (FR-4, P1) — Coverage + weekly report.**
- **Given** a student's activity over a week, **when** the weekly job runs, **then** a per-subject coverage % and a performance report are generated automatically.

**US-6.2 (FR-16, P1) — Exam-readiness + study-next.**
- **Given** per-SLO mastery (BKT) and past-paper frequency, **when** computed, **then** a single exam-readiness score is shown and a "study-next" list is ranked by likely mark gain (frequency × (1 − mastery)).

### Epic 7 — Classroom & Spaces

**US-7.1 (FR-10, P1) — Enroll & build quizzes.**
- **Given** a teacher, **when** they create a space and share a join code, **then** students who enter the code are enrolled; **when** they build a quiz, **then** they can tag it by subject/topic.

**US-7.2 (FR-11, P1) — Post-quiz collective weak areas.**
- **Given** a completed quiz, **when** the report is generated, **then** collective weak topics are ranked by frequency of incorrect answers and both collective and individual views are available (subject-scoped to the teacher).

### Epic 8 — Security, Rate-Limiting & Pipeline

**US-8.1 (FR-13, P1) — Vet every skill/MCP.**
- **Given** a new/updated skill or MCP server, **when** it is submitted, **then** it is scanned, any claim-vs-actual capability mismatch is flagged, and it is admitted only with an AgentSBOM entry; a mismatch blocks admission.

**US-8.2 (FR-14, P0/P1) — Rate limits.**
- **Given** a user/IP exceeding the configured rate, **when** they call the model/tools, **then** requests over the limit receive HTTP 429; quotas are configurable per user/IP.

**US-8.3 (FR-12, P2) — Source-checked auto-update.**
- **Given** a newly released syllabus/textbook, **when** the pipeline ingests it, **then** it is used only after its provenance is checked; unverified sources are quarantined and never auto-ingested.

---

## 9. Domain Data Model

This is a **product-level** entity model — the seed for the TDD database schema (§30). Attributes are indicative, not final DDL.

### 9.1 Identity & roles
- **User** — `id, email, password_hash, status, created_at`; has exactly one primary **Role**.
- **StudentProfile** — `user_id, board (PCTB|STBB), class (9–12), student_group, medium (EN|UR), language_pref`. `student_group` ∈ {science, computer} for Classes 9–10 and {pre_medical, pre_engineering, ics} for Classes 11–12 (§2.4.1); a constraint rejects mismatched class/group pairs.
- **TeacherProfile** — `user_id, subject_scope`.
- **ParentProfile** — `user_id`.
- **AdminProfile** — `user_id, admin_scope`.
- **GuardianLink** — `parent_user_id, student_user_id, status (pending|verified|revoked), verified_at`; enforces the class-based parental gate (§4.3).
- **TwoFactorEnrollment** — `user_id, method (totp|email_otp), status (pending|active|disabled), totp_secret_encrypted, confirmed_at, last_used_at, failed_attempts, locked_until`; one per user (SEC-14). The secret is stored encrypted and is never readable through the API after enrolment.
- **TwoFactorBackupCode** — `id, user_id, code_hash, used_at`; 10 issued per enrolment, **hashed** and single-use.
- **SubscriptionPlan** — `code, name, price_minor, currency, billing_interval, is_active`; reference data. One row in v1 (`standard`, Rs. 999/month). Prices are held in **minor units** so money is never a float (§2.6).
- **Subscription** — `id, user_id, plan_code, status (trialing|active|past_due|canceled|expired), trial_ends_at, current_period_end`; **one per user**. `trial_ends_at` defaults to 14 days and is the single definition of trial length. A **missing** record means no access, not a trial (§2.6 MON-2).
- **OAuthIdentity** — `id, user_id, provider (google|microsoft), provider_user_id`; unique per `(provider, provider_user_id)` and per `(user_id, provider)`. Reserved for **FR-A6**, which is deferred — nothing writes to it in v1.
- **Institution** *(optional)* — `id, name`; institutions attach via spaces (§15).

### 9.2 Classroom & collaboration
- **ClassroomSpace** — `id, owner_user_id (teacher|parent), subject_scope, status`.
- **JoinCode** — `id, space_id, code, revoked, expires_at`.
- **Enrollment** — `space_id, student_user_id, joined_at, left_at` (join = consent; leaveable).
- **Announcement** — `id, space_id, author_user_id, body, created_at`.

### 9.3 Curriculum & knowledge base
- **Board**, **ClassLevel**, **Subject**, **Chapter** — curriculum taxonomy. A **Subject** is defined **once per (board, class)** and carries its `content_strategy` (§2.4.2), so shared subjects such as English are never duplicated per group.
- **SubjectGroup** — `subject_id, student_group`; records which elective groups take each subject (§2.4.1). Drives per-student subject lists, coverage, and exam-readiness.
- **SLO** (Student Learning Outcome) — `id, chapter_id, code, text, effective_from_year, retired_at`; the atomic mastery/coverage unit. SLOs are **soft-retired, never deleted**, so historical mastery keeps its meaning across curriculum years.
- **CurriculumItem** — `id, board, class, subject, chapter, exercise, question, worked_solution, slo_ids[]`.
- **TextbookFigure** — `id, source_ref, caption_ocr, chapter_id, slo_ids[], embedding_ref` (indexed by Qwen2.5-VL).
- **KBDocument** — `id, board, curriculum_year, source_uri, provenance_status, version, integrity_hash`.
- **UrduNoteItem** — `id, type (couplet|prose|essay|letter|grammar), schema_fields (couplet→ couplet/meaning/tashreeh/context/devices/central_idea/poet/reference), source`.
- **GlossaryTerm** — `id, board, subject, en_term, standard_urdu_term`.
- **PastPaper** — `id, board, class, subject, year`; **Question** — `id, pastpaper_id, slo_ids[], difficulty_ref`.

### 9.4 Assessment & analytics
- **Quiz** — `id, space_id, subject, topic_tags[], time_window, one_attempt=true, shuffle=true, source (teacher|agent_draft)`.
- **QuizAttempt** — `id, quiz_id, student_user_id, state, started_at, submitted_at, score`.
- **AttemptAnswer** — `id, attempt_id, question_id, response, correct` (answer keys server-side only).
- **MasteryEstimate** — `student_user_id, slo_id, p_mastery (BKT), updated_at`.
- **ItemDifficulty** — `question_id, irt_params`.
- **CoverageRecord** — `student_user_id, subject_id, coverage_pct`.
- **ExamReadinessScore** — `student_user_id, subject_id, score, expected_marks, computed_at`.
- **Report** — `id, type (weekly|quiz|parent), scope, payload, generated_at`.

### 9.5 Tutor & multimodal
- **ChatSession** / **Message** — conversation history (grounding + weak-signal for mastery).
- **VisualAid** — `id, message_id, kind (figure|katex|mermaid|chart|functionplot|curated|text), payload, sandboxed=true`.

### 9.6 Security & platform
- **Skill** / **MCPServer** — `id, name, source, version, status (submitted|admitted|blocked)`.
- **PermissionManifest** — `id, skill_id, granted_scopes[]` (least-privilege).
- **AgentSBOMEntry** — `id, component_id, provenance, permissions, hash, admitted_at`.
- **VettingResult** — `id, component_id, scan_findings, claim_vs_actual, verdict`.
- **AuditLog** — `id, actor_user_id, action, target, tool_call_ref, timestamp` (who/what/when).
- **RateLimitBucket** — `key (user|ip), tokens, window` (Redis-backed).
- **ApiRequestLog** — `id, request_id, actor, role, method, endpoint, path, status_code, message, latency_ms, ip, timestamp`; every API call logged, daily-partitioned, surfaced per-day on the Admin panel (TEL-5). Distinct from `AuditLog`.

### 9.7 Key relationships
User 1–1 profile; Parent M–N Student via GuardianLink; Teacher/Parent 1–N ClassroomSpace; Space M–N Student via Enrollment; Subject 1–N Chapter 1–N SLO; CurriculumItem/Question M–N SLO; Student 1–N MasteryEstimate (per SLO); Quiz 1–N QuizAttempt 1–N AttemptAnswer; Skill 1–1 PermissionManifest, 1–1 AgentSBOMEntry.

---

## 10. State Machines

**10.1 QuizAttempt:** `NotStarted → InProgress → (Submitted | AutoSubmitted[on timeout]) → Graded → Reported`. Guards: one attempt per student; server-side keys; items shuffled; entry blocked outside the time window.

**10.2 ClassroomSpace:** `Created → Active → (Archived)`. JoinCode: `Active → (Revoked | Expired)`. Enrollment: `Joined → (Left | Removed)` (join = consent).

**10.3 GuardianLink (parental gate):** `Invited → (Verified | Expired | Revoked)`. Class 9–10 student tutor access requires `Verified`.

**10.4 KBDocument ingestion (self-update):** `Detected → ProvenanceCheck → (Quarantined[fail] | Parsing[pass]) → Indexed → IntegrityVerified → Live`; new **board+year version** on each refresh.

**10.5 Skill/MCP vetting:** `Submitted → Scanning → (Blocked[mismatch/over-privilege] | ManifestAssigned) → Sandboxed → Admitted(AgentSBOM)`; runtime: `Admitted → (Suspended[guardrail violation])`.

**10.6 Subscription (§2.6):** `Trialing → (Active | Expired)`; `Active → (PastDue → (Active | Canceled)) | Canceled`; `Expired → Active` on subscribing. Learning access requires `Trialing` or `Active`. **No record at all is not a state** — it is treated as no access (MON-2).

**10.7 Onboarding (derived, §6.1):** `EmailVerificationPending → TwoFactorEnrollmentPending → [GuardianLinkPending, Classes 9–10] → Active ⇄ PlanSelectionPending`. This is the one state machine here that is **not** a forward-only progression: the last transition is bidirectional, because a trial lapsing returns an already-active student to plan selection. It is **derived** from §9.1 entities rather than stored, so it has no column and no migration.

---

## 11. AI / Model Requirements

### 11.1 Model registry (per stage)

| Stage | Model (from proposal) | Hosting (hybrid) |
|---|---|---|
| Orchestrator / understanding / generation | Qwen2.5 / Qwen3 (+ Urdu LoRA) | self-host or hosted API [PROPOSED per §2.5] |
| Speech-to-text (voice input) | Whisper (large-v3 / Urdu fine-tune) | self-host |
| Guardrails | Prompt Guard 2 / Llama Guard 3 | self-host |
| Retrieval (cross-lingual) | BGE-M3 | self-host |
| Rerank | BGE-reranker-v2-m3 | self-host |
| Figure indexing (offline) | Qwen2.5-VL | self-host (batch) |
| Visuals (code-rendered) | LLM → Mermaid / SVG / chart-JSON / KaTeX | via orchestrator |
| Text-to-speech (output) | Fish Audio S2 Pro (Apache-2.0) | self-host or low-cost API |
| Lip-sync avatar | MuseTalk v1.5 | self-host (GPU) |

### 11.2 Requirements
- **AI-M1 — Hybrid hosting:** self-host models where GPU budget allows; use hosted APIs for heavy/uncertain ones; the platform must run without dependence on any single paid API (NFR portability, §18).
- **AI-M2 — Retrieval-first grounding:** answers must be grounded in retrieved curriculum content; the agent prefers verified textbook content over free generation.
- **AI-M3 — Generate-in-language (not translate-after):** Urdu answers are generated directly in Urdu grounded in the retrieved (English) source, with the glossary applied — never post-hoc machine translation.
- **AI-M4 — Controlled skills, not open autonomy:** the agent operates via explicit, permissioned skills (proposal limitation §1.7); no unrestricted multi-step autonomy.
- **AI-M5 — Fallbacks:** each model stage has a defined fallback (§20).
- **AI-M6 — Evaluation:** answer correctness is evaluated against board answer keys; Urdu-TTS intelligibility is sample-validated before release (§22).

---

## 12. Content, Data & Language Requirements

### 12.1 Flagship build-own dataset
No open, structured dataset of Pakistani board curricula exists; building a **multi-board (PCTB/STBB), class- and chapter-indexed** dataset of questions, worked solutions, SLO links, and indexed textbook figures is part of the project's contribution. We **reuse** mature open datasets where they exist and **build-own** the curriculum dataset.

### 12.2 Content strategies (four)
Every subject carries a `content_strategy` (§2.4.2) that the agent router reads to decide **whether generation is permitted at all**.

- **`branch_a_english_source` — dual-medium subjects (Maths, Physics, Chemistry, Biology, Computer Science, Islamiat, Pakistan Studies):** keep **one English-medium KB** (digital text) as the source of truth; retrieval is **cross-lingual** (BGE-M3) so an Urdu question finds the right English content; the answer is **generated in the student's language**; a **board-aligned Urdu terminology glossary** keeps Urdu wording identical to the student's book. These subjects are all published in parallel English and Urdu editions with the same syllabus, so a single source of truth serves both. Halves the data work.
- **`branch_b_urdu_native` — Urdu:** build a **structured Urdu notes corpus**, answered **retrieval-first**. Objective items (tashreeh, khulasa, markazi khayal, fixed questions) are returned **word-for-word**; productive items (essay/letter) are built from a **template with controlled length**, using a strong Urdu model (Qwen / UrduLLaMA-Alif) only to fill the scaffold. Prefer notes that are digital and openly available, board-issued, or teacher-reviewed.
- **`english_language` — English:** grammar, essay, letter and comprehension items answered from a structured corpus against fixed exam formats, mirroring the Urdu approach but in English.
- **`religious_verbatim` — Quran Translation:** **retrieval only.** The board-approved translation is returned **word-for-word**; the model may format or locate a verse but must never compose, paraphrase, or interpolate. A retrieval miss produces an explicit "not found" rather than a generated answer. This is a correctness *and* ethical requirement — see **FR-17** and the risk entry in §24.

### 12.3 Content schemas
- **Poetry (per couplet):** couplet, literal meaning, tashreeh, context, poetic devices, central idea, poet, reference.
- **Prose:** khulasa, tashreeh, question-and-answer.
- **Productive bank:** model essays and letters tagged with structure and length; grammar & idiom lexicon.
- **Curriculum item:** question + worked solution + SLO links + board/class/chapter/exercise indices.
- **Textbook figure:** cropped image + OCR caption + chapter/SLO link + embedding.

### 12.4 Dataset & acquisition plan (from proposal Table 3.4)

| Data category | Source(s) | Strategy | Purpose |
|---|---|---|---|
| Curriculum content (non-language) | English-medium textbooks (digital text) + board-aligned Urdu terminology glossary from parallel past papers | Build-own | Curriculum-exact answers in both languages, step-by-step solutions |
| Urdu-subject notes corpus | Per-couplet tashreeh, model essays (with lengths), grammar/idiom lexicon; digital/open/board-issued or teacher-reviewed | Build-own | Urdu-subject answers (retrieval-first + templates) |
| Textbook figures | Cropped from textbook PDFs, captions via OCR, linked to chapter/SLO, embedded (indexed by Qwen2.5-VL) | Build-own | Retrieval-first visual aids |
| Board past papers & MCQ banks | Public past papers/MCQs (last 5 years; e.g. pastpapers.pk, ilmkidunya, mathcity.org) | Reuse + extend | Practice questions; QA benchmark; SLO-level frequency for adaptive quizzes & exam-readiness |
| Urdu / Roman-Urdu instruction & QA | UrduLLaMA, Alif Urdu-Instruct, roman-urdu-alpaca-qa-mix | Reuse | Generate-in-Urdu; adaptive language |
| Voice (TTS + STT) | Fish Audio S2 Pro (TTS, self-hosted); Whisper (STT); Common Voice Urdu | Reuse | Avatar narration (EN/UR); spoken-input transcription; Urdu STT fine-tune/eval |

### 12.5 Versioning, provenance & ethics
- **Versioning:** the dataset/KB is versioned by **board + curriculum year**; the self-updating pipeline re-reads revised textbooks/SLOs after a **source check**, so the KB follows syllabus changes without a full rebuild.
- **Provenance:** new sources are used only after provenance/signature verification; KB integrity is verified (§16, O6).
- **Licensing & ethics:** textbook content used as **fair educational use with attribution**; personal data anonymized; data about minors kept to a minimum and **never used to train models** (§26).

---

## 13. Assessment & Analytics Requirements

- **AN-1 — SLO as the unit:** progress, coverage, and frequency are measured at the **SLO (concept)** level, not by exact question wording.
- **AN-2 — Past-paper frequency:** mine 5 years of past papers, cluster questions by meaning (BGE-M3 embeddings) onto SLOs, filter against the **current syllabus**; quizzes draw from the highest-frequency, exam-likely SLOs (FR-15).
- **AN-3 — Per-SLO mastery (BKT):** track a mastery estimate per SLO with **Bayesian Knowledge Tracing** (interpretable; models guessing and slips — important for MCQs). Mastery is fed by quizzes, chat behavior (repeated questions on a topic signal weakness), and coverage, and **decays** with light spaced repetition.
- **AN-4 — Difficulty calibration (IRT):** calibrate item difficulty from past-paper miss-rates with **Item Response Theory**.
- **AN-5 — Exam-readiness:** combine per-SLO mastery with past-paper frequency into a single **exam-readiness** score and an **expected-marks** estimate.
- **AN-6 — Study-next ranking:** rank a "study-next" list by **frequency × (1 − mastery)** — biggest mark gain first; drives the student revision plan and the teacher/parent reports.
- **AN-7 — Coverage:** compute syllabus **coverage %** per subject; auto-generate a **weekly** performance report (FR-4).
- **AN-8 — Reports:** quiz report (per-student score + class collective weak areas, subject-scoped); weekly student report; parent all-subject report + how-to-help.

---

## 14. Multimodal Requirements

- **MM-1 — Visual decision ladder (retrieval-first):** (1) retrieve the indexed textbook figure; else (2) render a typed code-based visual — **KaTeX** (math), **Mermaid** (diagrams/processes), **chart-JSON** (Chart.js/Recharts), **function-plot/JSXGraph** (equations); else (3) a curated image; else (4) text. Routing is gated by a **retrieval similarity threshold**.
- **MM-2 — Safe rendering (LLM05):** all model-written visual code is treated as **untrusted** and rendered in a **sandboxed iframe with CSP and DOMPurify**; output kept to safe, typed formats filled from ready templates (open/local models are weak at free-form SVG/HTML). Diffusion image-gen is a **stretch** (Gemini API considered only if aligned).
- **MM-3 — TTS/avatar:** the avatar speaks EN/UR via **Fish Audio S2 Pro** (self-hostable, ~100–150 ms, one voice for both languages via cross-lingual cloning); audio drives the on-screen avatar via **MuseTalk v1.5** lip-sync. Voices are cloned **only with consent**.
- **MM-4 — STT:** spoken Urdu/English/Roman-Urdu input is transcribed by **Whisper** (large-v3 / Urdu fine-tune).
- **MM-5 — Urdu-TTS risk & fallback:** Urdu is not a top-tier TTS language; pronunciation of technical words is sample-validated before release; fallback to a native **ur-PK** cloud voice or a local Urdu TTS model (§20).

---

## 15. Classroom & Collaboration Requirements

- **CL-1 — Spaces & join codes:** a **teacher** creates a **space** and shares a unique, **revocable** join code; the student enters the code to join. **Joining is the consent step.** The student can see who can view them and can **leave any space at any time**; every viewer is **read-only**. *(Parents create no spaces — their visibility comes from a verified guardian link, §4.3. Changed in v0.3.5.)*
- **CL-2 — Teacher view (subject-scoped):** a teacher declares the subject they teach; reports are limited to that subject (least-privilege). Each week the system produces a **class digest** — from **practice results and coverage gaps** — naming the topics/weak points to focus on. *(Through v0.3.4 this read "from chat history, practice results, coverage gaps". Chat content is **owner-only** with no teacher read path (§4.2), so the digest carries **no tutor-derived signal of any kind** — not conversation text and not counts derived from it. Corrected in v0.3.5.)*
- **CL-3 — Parent view (all subjects):** a linked parent gets an all-subject report of strengths/weak spots plus a short, curriculum-grounded **how-to-help** plan. The plan **recommends** actions for the student to take — revisit a chapter, practise specific questions, replay an explanation — and gives the parent **no control that opens any of them** on the student's account. *(Through v0.3.4 this listed "replay an avatar explanation" as a parent action, which §4.2 denies. Corrected in v0.3.5.)*
- **CL-4 — Secure assessments:** teachers create time-limited, Google-form-style quizzes (optionally **agent-drafted** from the chapter/SLOs, then **teacher-approved**). Delivery is secure: fixed time window with **auto-submit**, **one attempt**, **shuffled** questions, and **answer keys kept server-side** (never sent to the browser); auto-graded. After a quiz the teacher gets each student's score and a class weak-point summary.
- **CL-5 — Announcements:** teachers can post one-way announcements to a space. Direct guardrail-moderated student↔teacher chat is a **stretch goal** (out of v1 scope).
- **CL-6 — Institutional attach:** institutions use the platform through the classroom layer — teachers create spaces and roll out access via join codes; **[PROPOSED — confirm]** no separate SSO/multi-tenant system in v1 (§2.5).

---

## 16. Security Requirements

Security is a **first-class, built-in** capability (proposal title: "Secure & Agentic … Audited AI Skills & Secure MCP Servers"). Requirements use `SEC-N` and are mapped to OWASP LLM Top 10 (2025) and OWASP Agentic/Skills Top 10 (2026). **Baseline safety** (SEC-1, SEC-2, SEC-3) ships in **P0** because it is intrinsic to safely shipping the agentic tutor; the **full** Secure Skills & MCP Layer (SEC-4…SEC-8) is **P1**.

### 16.1 Requirements
- **SEC-1 (P0) — Input guardrail:** every input is checked by Prompt Guard 2 / Llama Guard 3 before it reaches the agent; unsafe input is blocked.
- **SEC-2 (P0) — Output guardrail + safe rendering:** output is checked by Llama Guard 3; all model-written visual code renders in a **sandboxed iframe with CSP + DOMPurify** (typed formats only).
- **SEC-3 (P0) — Rate limiting & quotas:** Redis token-bucket per user/IP; over-limit → HTTP 429; configurable quotas + concurrency caps (see §17).
- **SEC-4 (P1) — Skill/MCP vetting scanner:** every skill/MCP server is scanned before use; **claim-vs-actual capability mismatch** is flagged and blocks admission (FR-13).
- **SEC-5 (P1) — Least-privilege manifests:** each admitted component gets a permission **manifest** granting only the scopes it needs.
- **SEC-6 (P1) — Sandboxing:** skills/MCP run isolated (container/CSP sandbox).
- **SEC-7 (P1) — Runtime guardrails:** each tool call is monitored at runtime; violations are blocked and the component can be suspended.
- **SEC-8 (P1) — AgentSBOM:** an **AgentSBOM** records each component's provenance, permissions, and hash; only admitted-with-SBOM components run.
- **SEC-9 (P1) — KB-poisoning defense:** new curriculum sources are ingested only after **provenance/signature** verification and **KB integrity** checks (FR-12); unofficial/unsigned documents are quarantined.
- **SEC-10 (P0) — Data protection & PII:** **AES-256 at rest, TLS 1.3 in transit**; RBAC; **minimal PII** collection; minors' data minimized (§26).
- **SEC-11 (P1) — Audit logging:** who/what/when for tool calls and data access (§21) with tamper-evident storage.
- **SEC-12 (P1) — Supply-chain hardening in CI:** static analysis (**Semgrep**), policy-as-code (**OPA/Rego**), and artifact signing (**sigstore/cosign**) in the CI/CD pipeline; the Secure Skills & MCP scanner runs on every PR.
- **SEC-14 (P0) — Two-factor authentication (all roles):** every account must hold an active second factor before full access is granted (FR-A4). **TOTP** (RFC 6238, 6 digits, 30 s period) is the primary method, with **email-OTP** as an equal-standing alternative and **10 single-use backup codes** for recovery. Storage rules: the **TOTP secret is encrypted at rest** and never returned after enrolment; **backup codes are hashed** (argon2id) and never retrievable. Verification is **rate-limited and locked after repeated failures** (a 6-digit code is only 10⁶ combinations), each attempt is audited, and a used TOTP code cannot be replayed within its window. Password authentication alone never yields a full session — a correct password returns `200` with a `status` discriminator (`email_verification_required` | `two_factor_enrollment_required` | `two_factor_required`) and a short-lived challenge token; a wrong password returns `401`.
- **SEC-13 (P0) — Row Level Security (database-level authorization):** every table enforces RLS so the **database itself** filters rows by the acting user, independent of application code. Policies implement the §4.2 RBAC matrix: a student sees only their own data; a parent sees a linked child's data only through a **verified** guardian link; a teacher sees only students enrolled in their space **and** only subjects they are scoped to; chat content is **owner-only** with no teacher/parent/admin read path. Two hard guarantees: **answer keys are unreadable by the application role** (no policy grants access — NFR-8 backstop), and access **fails closed** if the acting user is not established. RLS is defense-in-depth beneath application authorization, not a replacement for it.

### 16.2 OWASP threat → requirement → acceptance mapping

| OWASP item | Requirement | Acceptance |
|---|---|---|
| **LLM01 — Prompt Injection** | SEC-1, SEC-4, SEC-7 | Malicious prompt / tool-call is blocked at input guardrail and tool-vetting; logged. |
| **LLM04 — Data & Model (KB) Poisoning** | SEC-9 | Unverified source never enters KB; provenance + integrity verified; poisoned doc quarantined. |
| **LLM05 — Improper Output Handling** | SEC-2 | Visual code executes only in sandbox (CSP/DOMPurify); no unsafe HTML/JS reaches the DOM. |
| **LLM10 — Unbounded Consumption / DoS** | SEC-3, §17 | Over-limit calls get HTTP 429; quotas + concurrency caps enforced. |
| **Agentic/Skills Top 10 — untrusted/over-privileged skills & MCP** | SEC-4…SEC-8, SEC-12 | Every component vetted, least-privileged, sandboxed, SBOM-recorded; over-privileged/malicious blocked. |
| **Sensitive-data exposure (minors)** | SEC-10, SEC-11, SEC-13, §26 | Encryption in transit/at rest; RBAC **plus database-level RLS**; minimal PII; audited access; chat content owner-only. |
| **Broken access control / IDOR** | SEC-13 | An application bug or leaked credential still cannot return another student's rows — RLS filters at the database. |
| **Credential stuffing / stolen password** | SEC-14 | A password alone never yields a session; a second factor is required for every role, rate-limited and audited. |

---

## 17. Platform, Rate-Limiting & Abuse Control

- **RL-1 (P0):** **Redis token-bucket** rate limiter **per user and per IP** on model and tool calls.
- **RL-2 (P0):** requests over the limit receive **HTTP 429**.
- **RL-3 (P1):** quotas are **configurable** (per user/IP) by Admin; **concurrency caps** protect against runaway model use.
- **RL-4 (P1):** sliding-window counters complement token-bucket for burst control.
- **Rationale:** stops flooding/DoS and runaway compute cost (**OWASP LLM10**); ties to SEC-3 and NFR availability.

---

## 18. Non-Functional Requirements

Verbatim from the proposal NFR table (Table 3.2), each with an added **verification method**.

| ID | Category | Requirement | Target / metric | Verification |
|---|---|---|---|---|
| **NFR-1** | Performance | Interactive chatbot latency | Median response **under 3 s** for cached curriculum queries | Load test on cached queries; measure median latency |
| **NFR-2** | Usability | Usable by students new to digital tools | Tasks done **without training**; multilingual UI. **Trade-off:** mandatory 2FA (SEC-14) adds friction for this cohort — mitigated by offering email-OTP as an equal method, backup codes, and admin-assisted recovery. Enrolment must be completable by a first-time user without help | Task-based usability test (untrained users), **including 2FA enrolment on a shared/basic device**; UI in EN/UR |
| **NFR-3** | Reliability | Checkable, bounded agent actions | **Per-step checking**; graceful degradation on failure | Fault-injection; verify degradation paths (§20) |
| **NFR-4** | Security | Skill/MCP checking + PII protection | **AES-256** at rest, **TLS 1.3** in transit; least-privilege manifests | Config audit; pen-test; manifest review |
| **NFR-5** | Availability / abuse-resistance | Rate-limited model and API calls | Redis token-bucket per user/IP; **HTTP 429** on exceed (LLM10) | Rate-limit test → assert 429 + quota behavior |
| **NFR-6** | Maintainability | Modular skills | Each capability is a skill that can be **tested on its own** | Per-skill unit/integration tests |
| **NFR-7** | Portability | Local/open model support | Runs on **open/self-hosted** models, no dependence on a paid API | Run core flow on self-hosted stack |
| **NFR-8** | Assessment integrity | Secure quiz delivery | Server-side answer keys; time-boxed with auto-submit; one attempt; shuffled items | Attempt-tampering test; verify keys never sent client-side |

---

## 19. Internationalization & Accessibility

- **I18N-1:** UI and content in **English, Urdu, and Roman-Urdu**; language switchable.
- **I18N-1a:** **English is the default for every visitor.** The interface language is **never negotiated** from the browser's language settings or a stored preference — a device configured for Urdu, which is unremarkable in this audience, must not be pushed into Urdu before the user has chosen. Language is an explicit choice, made through the switcher, and it persists through navigation because every route carries its locale.
- **I18N-2:** **RTL** layout for Urdu; correct rendering of Urdu script and mixed EN/UR content.
- **I18N-3:** accept both **Urdu script and Roman-Urdu** input without a separate transliteration step (model handles both).
- **I18N-4 (implementation rule):** **Urdu (`ur`) is the only right-to-left locale.** **Roman-Urdu is Latin script and stays left-to-right** — mirroring it would be a defect, not a feature. Mirroring must be achieved with **direction-agnostic layout primitives** (logical start/end spacing and alignment) rather than per-locale overrides, so a new screen is RTL-correct by construction instead of by remembering. Directional icons (arrows, chevrons) flip; non-directional ones (mail, lock, person) must not. Content that is inherently left-to-right inside an RTL page — one-time codes, backup codes, numerals in a countdown — is pinned LTR so its characters cannot reorder.
- **I18N-4a (implementation rule):** the RTL requirement is **enforced automatically, not by review**. Every source file is swept for physical direction properties (`ml`/`mr`, `pl`/`pr`, `left`/`right`, `text-left`/`text-right`, `border-l`/`border-r`); only logical equivalents are permitted. This is a rule about human attention, not about CSS: all fifteen supplied prototypes are written physically, so a class copied verbatim renders perfectly in English and quietly breaks the Urdu layout — a defect nobody sees until an Urdu-reading user does.
- **I18N-5 (identifier rule):** the stored language value and the web locale tag are **not the same string**. The database and API use `roman_ur` (the `language_code` enum). That is not a valid BCP-47 tag: locale-aware date, number and plural formatting rejects it, and `lang="roman_ur"` tells assistive technology nothing. The web layer therefore uses **`ur-Latn`** — the correct tag for Urdu in Latin script — and converts at the API boundary. Neither side changes for the other; the conversion lives in one place.
- **A11Y-1:** WCAG-oriented targets — sufficient contrast, keyboard navigation, readable typography for Urdu/English; captions/text alongside avatar audio.
- **A11Y-1a (implementation rule):** an **error is conveyed by icon, text and colour together**, never by colour alone, and is tied to its control so assistive technology announces it. A **countdown is announced coarsely, not per second** — a lockout or code-expiry timer that updates a live region every second interrupts a screen-reader user continuously for its whole duration, which technically satisfies "announced" while making the page unusable. The precise timer is presented visually and a separate live region reports "about N minutes left", changing only when the minute changes.
- **A11Y-1b (implementation rule):** where a step's whole purpose is one field — a one-time code, a backup code — **focus moves to that field**, and returns to it after a rejected attempt clears it. A rejected code that leaves focus on the submit button strands keyboard and screen-reader users on a control they have just been told did not work.
- **A11Y-2:** **Low-bandwidth / entry-device** friendliness — the responsive web UI must work on modest mobile browsers (target audience context, §3.1).

---

## 20. Error Handling, Fallbacks & Degradation

Graceful degradation is required at every model-dependent step (NFR-3).

- **Visual aid:** textbook figure → typed code-render → curated image → text.
- **Voice/TTS:** Fish S2 Pro → ur-PK cloud voice / local Urdu TTS → text-only.
- **LLM:** primary model → secondary model → cached/curated answer; if grounding retrieval misses, the tutor states it lacks a curriculum-grounded answer rather than hallucinating.
- **Retrieval miss:** below similarity threshold → "no confident match" + closest items, never fabrication.
- **STT:** low-confidence transcription → ask the student to confirm/retype.
- **Quiz:** timeout → auto-submit; connection loss → resume within the window (one attempt preserved).
- **User-facing error states:** every failure yields a clear, localized message (EN/UR) and a safe next action.
- **Every documented failure has a designed state.** A screen that can render its success path but not its failure paths is incomplete. Clients branch on the machine-readable **error code**, never on the message text — messages are translated and will change — and an unrecognised code must still render a usable state rather than a blank screen.

---

## 21. Telemetry, Logging & Auditability

- **TEL-1:** capture product events needed for KPIs (§22) — query latency, retrieval groundedness, answer feedback, quiz outcomes, coverage/mastery updates, adoption.
- **TEL-2 — Audit logs:** record **who/what/when** for every tool/skill/MCP call and every access to student data (SEC-11); tamper-evident.
- **TEL-3 — Minors-safe logging:** logs minimize PII; student chat content is not exposed to teachers/parents/admin (only the student sees their own; admin sees audit metadata only, §4.2).
- **TEL-4:** security events (guardrail blocks, 429s, vetting rejections, quarantines) are logged and surfaced to Admin.
- **TEL-5 — Endpoint access logging + admin daily view:** **every** API call is logged with its **endpoint, HTTP method, status code, message, timestamp, actor, and latency**. The Admin panel shows **each day's logs** (per-endpoint counts, error rates, and messages) with drill-down. This operational access log is separate from the security audit log (TEL-2). *Serves the admin observability need; entity `ApiRequestLog` (§9.6); TDD `api_request_log` + `fact_endpoint_calls`.*

---

## 22. Success Metrics / KPIs

Targets marked **[PROPOSED]** start from proposal NFR targets and are to be confirmed (§2.5).

| KPI | Proposed target | Measurement |
|---|---|---|
| Cached-query latency | Median **< 3 s** (NFR-1) | Instrumented latency on cached curriculum queries |
| Retrieval groundedness | **[PROPOSED]** ≥ 90% of answers cite retrieved curriculum | Automated grounding check on a QA benchmark |
| Answer correctness | **[PROPOSED]** ≥ 85% vs board answer keys | Eval against past-paper answer keys |
| Per-SLO mastery calibration | **[PROPOSED]** calibration error ≤ target | Compare BKT predictions vs held-out outcomes |
| Coverage tracking | Coverage % available per subject (FR-4) | Verify weekly report generation |
| Usability | Core tasks completed **without training** (NFR-2) | Untrained-user task test |
| Urdu-TTS intelligibility | Sample **passes** before release (MM-5) | Human sample validation |
| Assessment integrity | 0 client-side key leaks; tamper attempts blocked (NFR-8) | Security test on quiz delivery |
| Security posture | 100% of skills/MCP have an AgentSBOM entry; over-privileged blocked | Vetting/SBOM audit |

---

## 23. Future Roadmap (Priority Tiers)

Spread across **~1 full academic year**, following Spec-Driven Development (**constitution → specify → plan → tasks → implement**), tracked on a project board. Version control: `main` protected; feature branches `feature/<epic>-<desc>`; PR = unit of review; only the team lead merges after CI passes (tests + Secure Skills & MCP scanner + container build).

### P0 — Individual Student Tutor MVP *(demo-able core)*
Auth + student dashboard (Epic A, K) · Board Curriculum Chatbot EN/UR/Roman-Urdu, class/board-adaptive, text+voice-in (B) · partial Urdu-Lazmi (C) · **Quran-Translation verbatim mode (C2)** · retrieval-first visual aids + avatar/voice (D) · **baseline safety** SEC-1/2/3 + rate-limit (I) · curriculum KB across both boards × all classes (subject breadth per data rollout).
**Definition of Done (P0):** a student can self-serve sign up, verify their email, **enrol a second factor** (FR-A4), clear the parental gate if Class 9–10, and reach the dashboard on an active trial — then ask a curriculum question in any of the 3 languages and receive a grounded answer + retrieval-first visual + talking avatar, all within guardrails and rate limits. **A student whose trial has lapsed is routed to plan selection** (FR-A5) rather than into the product. *(Through v0.3.4 this omitted 2FA and plan selection, both of which are P0; corrected in v0.3.5.)*

### P1 — Assessment, Classroom & Full Security
Adaptive quiz engine (E: FR-3/15) · coverage + exam-readiness reports (F: FR-4/16) · Classroom & Spaces (G: FR-10/11) · parent reports · **full Secure Skills & MCP Layer** (H: FR-13, SEC-4…8/11/12).
**Definition of Done (P1):** teachers run secure quizzes and read subject-scoped collective weak-area reports; students see exam-readiness + study-next; every skill/MCP is vetted, least-privileged, sandboxed, and SBOM-recorded.

### P2 — Breadth, Automation & Stretch
Self-updating curriculum pipeline (J: FR-12, SEC-9) · admin console depth · broaden the full PCTB+STBB × 9–12 × all-subjects matrix · stretch (diffusion image-gen; direct student↔teacher chat; advanced analytics).
**Definition of Done (P2):** new syllabi ingest automatically after provenance checks; the curriculum matrix is broadened; admin/security tooling is complete.

---

## 24. Risk Assessment

From proposal Table 3.3, with **owner** and **trigger** added for tracking.

| Risk | Likelihood | Impact | Mitigation | Owner | Trigger |
|---|---|---|---|---|---|
| Curriculum hard to digitize | Medium | Medium | Use digital text where possible; OCR only as fallback; priority subjects first | Data lead | Subject/board data not digitally available |
| Urdu terminology comes out wrong | Medium | High | Board-aligned glossary + generate-in-Urdu (not translate-after) | NLP lead | Glossary miss / mistranslation reported |
| Malicious third-party skill | Medium | High | Secure Skills & MCP Layer: scan, manifest, sandbox before use | Security lead | Vetting flags claim-vs-actual mismatch |
| Auto-update poisoning | Low | High | Check source provenance/signature; verify KB integrity | Security lead | Unsigned/unofficial source detected |
| Denial-of-service / runaway model use | Medium | High | Redis per-user/IP rate limiting + quotas + concurrency caps (LLM10) | Platform lead | Abnormal request/compute spike |
| Urdu TTS quality (not top-tier) | Medium | Medium | Validate a sample; ur-PK cloud voice / local Urdu TTS fallback | Multimodal lead | Sample validation fails |
| Low teacher adoption of classroom/quiz tools | Medium | Medium | Minimal teacher UI (quiz + report viewing only); pilot one section first | Product lead | Low teacher activation in pilot |
| Student performance data mishandled | Low | High | AES-256 at rest, TLS 1.3 in transit; RBAC **+ database RLS (SEC-13)**; minimal PII collection | Security lead | Access anomaly / audit finding |
| **Inaccurate or paraphrased religious content** (Quran Translation, Islamiat) | Low | **Critical** | Quran Translation is **retrieval-only, verbatim** with generation disabled (FR-17); explicit "not found" on retrieval miss; board-approved sources only, teacher-reviewed | Content lead | Any generated/paraphrased religious text detected in evaluation |
| **2FA locks students out** (no smartphone, shared device, lost codes) | **Medium** | High | Email-OTP offered as an equal method; 10 backup codes at enrolment; admin-assisted recovery with identity verification; temporary lock on failure, never permanent | Product lead | Support requests or drop-off at the enrolment step |
| Student measured against subjects they don't take | Medium | Medium | Elective-group model (§2.4.1); coverage and exam-readiness computed only over the student's group subjects | Data lead | Coverage % looks implausible for a group |

**Project-level risk (added):** P0 breadth (both boards × all classes) is data-intensive — the binding constraint is curriculum digitization (proposal §1.7). Schedule/coverage tracked against the data-acquisition plan (§12).

---

## 25. Dependencies

### 25.1 External
- **Platform:** **Supabase** (managed PostgreSQL + Row Level Security); Supabase CLI for versioned SQL migrations.
- **Frameworks/libraries:** React, Next.js, Tailwind CSS; Python, FastAPI, JWT (argon2id); LangGraph, MCP SDK; Redis; Celery; FAISS/ChromaDB; Mermaid.js, KaTeX, Chart.js/Recharts, function-plot/JSXGraph, DOMPurify.
- **Models:** Qwen2.5/Qwen3 (+Urdu LoRA), Llama 3, Mistral; Whisper; BGE-M3, BGE-reranker-v2-m3; Qwen2.5-VL; Fish Audio S2 Pro; MuseTalk v1.5; Prompt Guard 2, Llama Guard 3.
- **Security/DevOps:** Semgrep, OPA/Rego, sigstore/cosign, container sandbox; GitHub Actions, Docker.
- **Data sources:** PCTB/STBB textbooks & curriculum docs; public past papers/MCQs; UrduLLaMA, Alif, roman-urdu-alpaca-qa-mix; Common Voice Urdu.

### 25.2 Internal
- Python runtime; GPU compute (self-hosting; ~12 GB VRAM class for TTS, more for LLM/avatar) within budget; object/document storage; the build-own curriculum dataset (§12).

---

## 26. Compliance Considerations

- **26.1 Minors' data & parental consent:** the platform serves minors. Data about minors is minimized and **never used to train models**. The **class-based parental-consent gate** (§4.3) requires a verified parent for Class 9–10; joining a space is an explicit consent step; students can leave anytime.
- **26.2 Data protection:** AES-256 at rest, TLS 1.3 in transit, RBAC, least-privilege, minimal PII, audited access (SEC-10/11).
- **26.3 Licensing / fair use:** textbook content used as **fair educational use with attribution**; prefer openly available, board-issued, or teacher-reviewed material; respect source licensing.
- **26.4 Institutional use:** institutions deploy via the classroom layer; recommended to inform students/parents of data handling and obtain appropriate consents.
- **26.5 Minors as the subscriber of record — [OPEN, needs supervisor review]:** access is paid (§2.6) and the **student** is the party selecting the plan, including Class 9–10 students who are typically 14–15. Minors generally lack capacity to enter a payment contract, and the platform already treats this cohort as requiring a verified guardian (§4.3). Two mitigations are available and neither has been adopted yet: route billing to the **linked guardian** for Classes 9–10, or require **guardian acknowledgement** of the subscription before it is charged. Flagged rather than resolved, because it is a legal question rather than a design one.

---

## 27. Support & Maintenance

- **27.1 Documentation:** `README.md` (setup), **this PRD**, `tdd.md` (technical design), per-skill docs, inline code docs.
- **27.2 Issue reporting:** via the project's issue tracker with description, repro steps, expected vs actual, environment.
- **27.3 Contribution & versioning:** branch-and-PR workflow (§23); semantic versioning of the PRD/TDD; dataset versioned by board+year.

---

## 28. Glossary

| Term | Definition |
|---|---|
| PCTB / STBB | Punjab Curriculum & Textbook Board / Sindh Textbook Board |
| NCP | National Curriculum of Pakistan |
| SLO | Student Learning Outcome — atomic concept unit for mastery/coverage |
| RAG | Retrieval-Augmented Generation |
| MCP | Model Context Protocol — open standard for calling external tools/skills at runtime |
| Agentic | An LLM agent that decomposes tasks and calls external skills/tools |
| BKT | Bayesian Knowledge Tracing — models per-SLO mastery (with guessing/slips) |
| IRT | Item Response Theory — calibrates item difficulty |
| Exam-readiness | Combined mastery × past-paper frequency score + expected marks |
| AgentSBOM | Agent Software Bill of Materials — provenance/permissions record per skill/MCP |
| LoRA | Low-Rank Adaptation — lightweight fine-tuning |
| CSP / DOMPurify | Content Security Policy / HTML sanitizer — safe rendering of untrusted output |
| Generate-in-Urdu | Answer written directly in Urdu grounded in retrieved source (not post-translated) |
| Elective group | The subject track a student follows — `science`/`computer` at Matric, `pre_medical`/`pre_engineering`/`ics` at FSc — which determines their subject list |
| Content strategy | Per-subject rule governing how the agent may answer: `branch_a_english_source`, `branch_b_urdu_native`, `english_language`, or `religious_verbatim` |
| Religious-verbatim | Retrieval-only mode (Quran Translation) where text is returned word-for-word and generation is disabled |
| RLS (Row Level Security) | PostgreSQL feature where the database itself filters rows per acting user, independent of application code |
| 2FA (two-factor authentication) | Requiring a second proof of identity beyond the password; mandatory for every role (SEC-14) |
| TOTP | Time-based One-Time Password (RFC 6238) — the rotating 6-digit code shown by an authenticator app |
| Email-OTP | A one-time code sent by email; the alternative second factor for users without a smartphone |
| Backup codes | Ten single-use recovery codes issued at 2FA enrolment, stored hashed and shown only once |
| Supabase | Managed PostgreSQL platform used as the OLTP database (Supabase Auth is not used; auth is application-managed) |
| Tashreeh / Khulasa / Markazi khayal | Urdu-subject exam forms: explication / summary / central idea |
| Mazmoon / Khat / Darkhwast | Essay / letter / application (Urdu productive items) |
| OWASP LLM/Agentic Top 10 | Standard risk lists for LLM and agentic applications |

---

## 29. Traceability Matrix

Proves 100% coverage: every objective (and its gap) maps to epics, FRs, tier, and downstream requirements.

| Objective | Gap | Epic(s) | FR-IDs | NFR/SEC | Tier |
|---|---|---|---|---|---|
| O1 Board Curriculum Chatbots | G-1, G-2 | B, C, C2, C3 | FR-1, FR-2, FR-7, FR-8, FR-9, **FR-17**, **FR-18** | NFR-1/2/7 | P0 (FR-9, FR-18 P1) |
| O2 Adaptive Quiz Engine | G-4 | E | FR-3, FR-15 | NFR-8 | P1 |
| O3 Coverage Tracking & Reports | G-5 | F | FR-4, FR-16 | NFR-2 | P1 |
| O4 Classroom Space | G-6 | G | FR-10, FR-11 | NFR-8 | P1 |
| O5 Multimodal Layer | G-3 | D | FR-5, FR-6 | SEC-2, NFR-3 | P0 |
| O6 Self-Updating Pipeline | G-7 | J | FR-12 | SEC-9 | P2 |
| O7 Secure Skills & MCP Layer | G-8 | H, I | FR-13, FR-14 | SEC-1…12, NFR-4/5 | P1 (baseline P0) |
| (Platform foundation) | — | A, K | FR-A1/A2/A3, **FR-A4**, **FR-A5**, **FR-A7**, **FR-A8**, FR-K1 *(FR-A6 deferred)* | SEC-10, **SEC-13**, **SEC-14**, NFR-2/6 | P0 (FR-A8 P1) |

---

## 30. PRD → TDD Derivation Map

| PRD section | Feeds TDD design area |
|---|---|
| §9 Data Model + §10 State Machines | DB schema, migrations, entity/relationship & lifecycle design |
| §7 FRs + §8 User Stories | Module/service design, API contracts, test plans |
| §11 AI/Model + §14 Multimodal + §12 Content/Data | Agent orchestration (LangGraph), skill/MCP interfaces, RAG pipeline, model-serving |
| §16 Security + §17 Rate-limiting | Security architecture, vetting/sandbox/manifest design, AgentSBOM format, threat model, gateway |
| §13 Assessment & Analytics | BKT/IRT services, quiz engine, reporting jobs |
| §15 Classroom + §4 RBAC | Spaces/authz model, consent & least-privilege enforcement |
| §18 NFRs + §21 Telemetry | Performance/reliability design, observability & audit |
| §23 Roadmap | Environments, CI/CD, deployment topology |

---

## 31. Appendices

### Appendix A — Security Requirement Priority Matrix (defensive)
| ID | Requirement | OWASP | Priority | Tier |
|---|---|---|---|---|
| SEC-1 | Input guardrail | LLM01 | Critical | P0 |
| SEC-2 | Output guardrail + sandboxed visuals | LLM05 | Critical | P0 |
| SEC-3 | Rate limiting & quotas | LLM10 | High | P0 |
| SEC-4 | Skill/MCP vetting scanner | Agentic/Skills | Critical | P1 |
| SEC-5 | Least-privilege manifests | Agentic | High | P1 |
| SEC-6 | Sandboxing | Agentic | High | P1 |
| SEC-7 | Runtime guardrails | Agentic | High | P1 |
| SEC-8 | AgentSBOM | Supply chain | High | P1 |
| SEC-9 | KB-poisoning defense | LLM04 | High | P1 |
| SEC-10 | Data protection & PII | Sensitive data | Critical | P0 |
| SEC-11 | Audit logging | — | Medium | P1 |
| SEC-12 | Supply-chain hardening (CI) | Supply chain | Medium | P1 |

### Appendix B — Environments & Quick-Start (to be finalized in TDD)
- **Frontend:** Next.js/React/Tailwind (responsive web). **Backend:** FastAPI (Python). **Data:** Supabase (managed PostgreSQL + RLS), Redis, FAISS/ChromaDB, star-schema analytics. **Migrations:** Supabase CLI (versioned SQL). **CI/CD:** GitHub Actions + Docker. Secrets as encrypted CI secrets. *(Concrete commands/topology specified in `tdd.md`.)*

### Appendix C — Testing Checklist (per epic, high level)
- [ ] A: signup, RBAC, parental gate (9–10 blocked until verified; 11–12 optional)
- [ ] A/2FA: enrolment required before full access; TOTP **and** email-OTP both work; backup code consumes single-use; replay of a used TOTP rejected; lockout after repeated failures is temporary; admin reset is audited
- [ ] B: exact-question retrieval, class-adaptive language, generate-in-Urdu + glossary
- [ ] C: couplet tashreeh template; essay/letter length & structure
- [ ] C2: Quran Translation returned verbatim; generation disabled; retrieval miss → explicit "not found" (FR-17)
- [ ] Groups: a Class-11 pre-medical student sees Biology not Mathematics; coverage computed only over group subjects
- [ ] RLS: student cannot read another student's rows; parent blocked without a verified link; answer keys unreadable by the app role (SEC-13)
- [ ] D: retrieval-first visual + sandboxed render fallback; avatar TTS + Urdu fallback
- [ ] E: adaptive difficulty; past-paper-frequency quiz filtered to syllabus
- [ ] F: weekly coverage report; exam-readiness + study-next ranking
- [ ] G: enroll via join code; secure quiz delivery; subject-scoped collective report
- [ ] H/I: skill/MCP vetting + AgentSBOM; rate-limit → 429
- [ ] J: source-checked auto-update; quarantine on provenance fail
- [ ] Cross-cutting: guardrails (LLM01/05), encryption, audit logging, i18n/RTL

### Appendix D — Model Registry
See §11.1 (per-stage model + hybrid hosting).

### Appendix E — Entity-Relationship Summary
See §9 (entities, attributes, relationships, lifecycle).

---

**Document End**

For questions or clarifications on this PRD, contact the EduBridge AI team or raise an issue in the project repository. This PRD is the source for `tdd.md`; changes here must be reflected downstream.





