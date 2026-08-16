# Backend API Endpoints

> Every route the backend actually serves, mapped to its handler, its service function and its row in
> `tdd.md` — followed by the **31 routes that `tdd.md` specifies and this repository does not
> implement.** This document doubles as the honest build-state record.
>
> **Snapshot: 2026-08-15.** Every `file:line` was opened and verified against this snapshot. Line
> numbers drift; when they do, the fix is to re-verify, not to delete the citation.

Related documents: [architecture.md](architecture.md) · [architecture.html](architecture.html) ·
[Database](database.html) · [`tdd.md`](../../tdd.md) · [`prd.md`](../../prd.md) ·
[`user-stories.md`](../../user-stories.md)

**Acronyms.** API — Application Programming Interface. RLS — Row-Level Security. RBAC — Role-Based
Access Control. JWT — JSON Web Token. TOTP — Time-based One-Time Password. OTP — One-Time Password.
SLO — Student Learning Outcome. SBOM — Software Bill of Materials. KB — Knowledge Base.

---

## 1. The count, and where it comes from

| | Count | How it was measured |
|---|---|---|
| Implemented routes | **18** | `grep -c "^@router\." backend/app/auth/routes.py` |
| Routers in the backend | **1** | `grep -rn "APIRouter(" backend/app --include=*.py \| wc -l` |
| Specified in `tdd.md` §3.1 | 23 | rows at `tdd.md:173-195` — `POST /api/auth/admin/login` was added to the table in phase 1b (FR-A2a) |
| Specified in `tdd.md` §7.2 | 26 | §7.2 consolidates §3.1 plus Tutor (§3.2, `tdd.md:239-241`), Quiz/Practice (§3.5, `tdd.md:299-304`), Spaces/Reports (§3.6, `tdd.md:321-326`) and its own 10 rows at `tdd.md:1032-1041` — where `GET /api/admin/rate-limits / PUT` (`tdd.md:1038`) is **two** endpoints |
| **Total specified** | **49** | 23 + 3 + 6 + 6 + 11 |
| **Specified but missing** | **31** | 49 − 18 — enumerated in §4 below. Unchanged: phase 1b added one specified endpoint AND implemented it in the same change |

**All 18 implemented routes live in one file**, `backend/app/auth/routes.py`. There is no second
router. `GET /health` (`backend/app/main.py:86`) is defined on the application object rather than the
router, sits outside `/api`, and is not one of the 49 — `tdd.md` does not specify it.

Everything is mounted under `settings.api_base_path`, default `/api` (`app/main.py:84`,
`app/core/config.py:36`).

---

## 2. Implemented routes

Grouped by feature. Every row: **route → handler (`routes.py:line`) → service function
(`service.py:line`) → request/response models (`schemas.py:line`) → the `tdd.md` §3.1 row it
satisfies.**

The rate-limit bucket column names the `enforce(...)` call in the handler; the limits themselves are
in [architecture.md §2.4](architecture.md#24-rate-limiter--appcoreratelimitpy117).

### 2.1 Reference data

| Route | Handler | Service | Models | Auth | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `GET /api/reference/enums` | `enums_endpoint` `routes.py:175` | `enums` `service.py:214` | `EnumsResponse` `schemas.py:114` | none | **none** | §3.1 row `tdd.md:173` |

`groups_by_class` is **derived** from the seeded `subject_group` table (`service.py:238-250`), not
hardcoded — a literal here would let the seed and the API drift apart silently. Readable as
`app_backend` only because migration `20260802140000` gave the reference tables a `SELECT` policy;
before that they were deny-all, which is why this endpoint once needed a privileged connection
(`routes.py:176-178`).

### 2.2 Registration and session

| Route | Handler | Service | Models | Auth | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `POST /api/auth/register` | `register_endpoint` `routes.py:95` | `register` `service.py:98` | `RegisterRequest` `schemas.py:35` → `RegisterResponse` `schemas.py:97` | none | `register` | §3.1 row `tdd.md:174` |
| `POST /api/auth/login` | `login_endpoint` `routes.py:104` | `login` `service.py:278` | `LoginRequest` `schemas.py:126` → `LoginResponse` union `schemas.py:152` | none | `login` | §3.1 row `tdd.md:175` |
| `POST /api/auth/admin/login` | `admin_login_endpoint` `routes.py:115` | `login` `service.py:278` with `admin_portal=True` | same `LoginRequest` → `LoginResponse` | none | `admin_login` | §3.1 row `tdd.md:176` |
| `POST /api/auth/refresh` | `refresh_endpoint` `routes.py:138` | `refresh` `service.py:412` | refresh cookie → `AccessTokenResponse` `schemas.py:151` | refresh cookie | `refresh` | §3.1 row `tdd.md:186` |
| `POST /api/auth/logout` | `logout_endpoint` `routes.py:157` | `logout` `service.py:444` | — (204) | `authenticated` | **none** | §3.1 row `tdd.md:187` |
| `GET /api/auth/me` | `me_endpoint` `routes.py:170` | `me` `service.py:525` | `MeResponse` `schemas.py:218` | `authenticated` | **none** | §3.1 row `tdd.md:191` |

**`register` issues no session.** It returns `onboarding_state: "email_verification_pending"`
(`service.py:210`) and queues the verification email (`service.py:200-204`). It binds the user id it
is about to create *before* inserting (`service.py:126`) because every profile policy and
`subscription_owner` are `WITH CHECK (user_id = app.current_user_id())`.

**`login` never returns a session either.** A correct password produces `200` with a `status`
discriminator naming the next step — one of three response shapes
(`EmailVerificationRequired` `schemas.py:130`, `TwoFactorEnrollmentRequired` `schemas.py:135`,
`TwoFactorRequired` `schemas.py:141`). A *wrong* password is `401 UNAUTHENTICATED`
(`service.py:320`, `:322`, `:324` — all three the same message, deliberately).

**`login` serves BOTH endpoints, and `admin_portal` is the only difference.** One function, not a
copy: the constant-time dummy-hash branch, the lockout ladder and the three response branches are
the whole security argument of this path, and a second copy would drift from them. The rule is
written as one exclusive-or (`service.py:346`) so it cannot be half-changed — an administrator is
refused at `/auth/login`, and everyone else is refused at `/auth/admin/login`.

> ⚠️ **BOTH REFUSALS ARE THE SAME 401 AS A WRONG PASSWORD**, with the same code and the same
> message, and the argon2 verify has already run in either case so the timing matches too. A `403`
> — or any distinguishable answer — would turn the public login form into an
> **administrator-enumeration oracle**: submit an address, read the status code. `tdd.md` §6.11
> forbids revealing an account fact "by body, status code, OR TIMING". Covered by
> `tests/unit/test_admin_login_gate.py`, which asserts the whole envelope against the
> wrong-password refusal captured from the same code path rather than asserting `== 401`.

> ⚠️ **THE UNLISTED URL IS NOT THE CONTROL.** `/api/auth/admin/login` is reached from a page the
> frontend serves at a server-only secret path (`ADMIN_LOGIN_PATH`, rewritten in `proxy.ts`). That
> keeps the entrance off the public site and nothing more; the role check above is the lock, and it
> holds whether or not the path is known.

**Its own rate-limit bucket** (`admin_login`, 5 per 5 minutes — `core/ratelimit.py`). Sharing
`login`'s would let anyone lock every administrator out of the product by hammering the public
form until the shared counter was exhausted.

**The continuations are deliberately SHARED.** `/auth/2fa/verify`, `/auth/2fa/resend`,
`/auth/refresh` and `/auth/logout` are not segregated: the challenge token the admin endpoint
issues is already bound to that user, so admin-only copies would add no security and would fork a
flow that is currently tested once.

**`refresh` rotates.** The new token goes **only** into the httpOnly, path-scoped
`refresh_token` cookie (`routes.py:146`) and is deliberately absent from the response body
(`routes.py:149-153`) so it cannot reach a log or a client store. Cookie `path` is
`/api/auth/refresh`, so it is not attached to every call.

> **A1 — FIXED, Phase 1 (2026-08-16).** `RegisterRequest.role` was an unrestricted `UserRole`, so
> **anyone could self-register as an administrator** and reach `active` in one request. It is now
> `RegistrableRole` (`models/enums.py`), which is `UserRole` minus `admin` — a narrower **type**
> rather than a validator, so the restriction appears in the generated OpenAPI schema and Pydantic
> rejects `admin` through `_validation_error_response` as the ordinary `400 VALIDATION_ERROR`
> envelope. Second layer: migration `20260816120000` narrows `app_user_insert` to
> `WITH CHECK (id = app.current_user_id() AND role <> 'admin')`, so the database refuses an
> administrator row to `app_backend` even if a future endpoint forgets the schema. **Promotion to
> administrator remains an owner-run SQL operation**, which that policy does not constrain.
>
> **A2 — FIXED, Phase 1 (2026-08-16).** `logout_endpoint` revoked the refresh rows and never cleared
> the cookie, so the browser kept presenting a revoked token; the next refresh read it as **token
> theft**, revoked the family and wrote a false `refresh_token_reuse_detected` audit row. Every
> ordinary sign-out fabricated a security incident. The cookie's attributes had been written out by
> hand at **three** set sites, and a browser only overwrites a cookie when name and path match — so
> the fix was `set_refresh_cookie()` / `clear_refresh_cookie()` in `dependencies.py`, one definition
> shared by all four call sites. `tests/unit/test_refresh_cookie.py` asserts each attribute of the
> deletion against the setter's own value rather than a literal, so the pair cannot drift.
>
> **Known defects D2 and D12.** Refresh rotation is three non-atomic statements
> (`tokens.py:118-122` then `issue_refresh_token`). `LoginRequest.password` (`schemas.py:124`) has
> **no `max_length`**, unlike `RegisterRequest.password` (`schemas.py:37`), and no token or code
> field anywhere has a length bound.

### 2.3 Two-factor authentication

| Route | Handler | Service | Models | Credential | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `POST /api/auth/2fa/enroll` | `two_factor_enroll_endpoint` `routes.py:188` | `two_factor_enroll` `service.py:726` | `TwoFactorEnrollRequest` `schemas.py:249` → `TwoFactorEnrollResponse` union `schemas.py:267` | `enrollment_token` **in body** | `2fa_enroll` + per-account `service.py:720` | §3.1 row `tdd.md:180` |
| `POST /api/auth/2fa/confirm` | `two_factor_confirm_endpoint` `routes.py:198` | `two_factor_confirm` `service.py:831` | `TwoFactorConfirmRequest` `schemas.py:270` → `TwoFactorConfirmResponse` `schemas.py:275` | `enrollment_token` **in body** | `2fa_confirm` + per-account `service.py:802` | §3.1 row `tdd.md:181` |
| `POST /api/auth/2fa/verify` | `two_factor_verify_endpoint` `routes.py:222` | `two_factor_verify` `service.py:945` | `TwoFactorVerifyRequest` `schemas.py:286` → `TwoFactorVerifyResponse` `schemas.py:292` | `pending_token` **in body** | `2fa_verify` + per-account `service.py:923` | §3.1 row `tdd.md:182` |
| `POST /api/auth/2fa/resend` | `two_factor_resend_endpoint` `routes.py:245` | `two_factor_resend` `service.py:1075` | `TwoFactorResendRequest` `schemas.py:299` → `TwoFactorResendResponse` `schemas.py:303` | `pending_token` **in body** | `2fa_resend` + per-account `service.py:1042` | §3.1 row `tdd.md:183` |

Short-lived, single-purpose tokens travel **in the request body**, not in an `Authorization` header
— one convention, with the header reserved for real sessions (`tdd.md:227`).

`/2fa/confirm` and `/2fa/verify` both set the refresh cookie (`routes.py:209`, `routes.py:233`) and
strip `refresh_token` from the response model (`routes.py:212-216`, `routes.py:236-241`).

`/2fa/verify` accepts three `type` values (`schemas.py:289`): `totp` (`service.py:942-951`),
`email_otp` (`service.py:953-967`) and `backup_code` (`service.py:969-986`). Backup codes are
argon2id-hashed, so verification must iterate the unused hashes rather than look one up
(`service.py:970-973`).

> **Known defect A9 — live today.** `/2fa/enroll` (`service.py:688`) **skips the lockout check** that
> `two_factor_confirm` performs at `service.py:824-826` — and it sends mail (`service.py:765`). A
> locked account can still be made to emit OTP messages.
>
> **Known defects D7 and D9.** The TOTP check passes a float where a `datetime` is expected.
> `/2fa/confirm` can trigger a pointless token refresh on the client.

### 2.4 Email verification and password reset

| Route | Handler | Service | Models | Auth | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `POST /api/auth/email/verify` | `email_verify_endpoint` `routes.py:256` | `verify_email` `service.py:1144` | `EmailVerifyRequest` `schemas.py:311` → `EmailVerifyResponse` `schemas.py:315` | `email_verify` token in body | `email_verify` | §3.1 row `tdd.md:176` |
| `POST /api/auth/email/resend` | `email_resend_endpoint` `routes.py:267` | `resend_email_verification` `service.py:1192` | `EmailResendRequest` `schemas.py:323` → 204 | none | `email_resend` | §3.1 row `tdd.md:177` |
| `POST /api/auth/password/forgot` | `password_forgot_endpoint` `routes.py:277` | `forgot_password` `service.py:1213` | `PasswordForgotRequest` `schemas.py:330` → 204 | none | `password_forgot` | §3.1 row `tdd.md:178` |
| `POST /api/auth/password/reset` | `password_reset_endpoint` `routes.py:287` | `reset_password` `service.py:1239` | `PasswordResetRequest` `schemas.py:334` → 204 | `password_reset` token in body | `password_reset` | §3.1 row `tdd.md:179` |

`/email/verify` returns an **onboarding-scoped** access token (`service.py:1111-1114`), not a
session token. `decode_access_token`'s default requires `type == "access"`
(`app/auth/security.py:98`), so this credential is rejected by every business route including
`/auth/me` — which is the `tdd.md` §3.1 rule that email verification alone must not become a
complete login. It also mints a fresh `two_factor_enrollment` token (`service.py:1118-1123`) so the
user can go straight to enrolment.

`/password/forgot` and `/email/resend` answer **identically for a known and an unknown address in
body, status and timing** (`tdd.md` §6.11). Both go through `_lookup_for_email_flow`
(`service.py:612`), which runs an argon2 verify on both branches (`service.py:630`) and treats a
suspended or deleted account exactly like an unknown one (`service.py:633`). The dominant timing term
— the synchronous HTTP call to the mail provider — is removed by dispatching off the request thread
(`app/auth/email.py:167`).

`/password/forgot` deliberately requires a **verified** address (`service.py:1169`): a reset link
mailed to an unverified one would let whoever controls that mailbox take an account they never proved
they own.

`/password/reset` revokes nothing in Python — the atomic swap lives inside
`app.consume_password_reset_token` (`service.py:1193`). A `false` return is turned into the right
error code by `_raise_for_token_status` (`service.py:583`): `410 TOKEN_EXPIRED` only for a token that
lapsed **unused**, `400 INVALID_TOKEN` for one already spent.

### 2.5 Guardian gate

All three are **role-gated, not guardian-gated** — a gated student must be able to reach them
(`routes.py:311`, `routes.py:325`, `routes.py:340`). Invite and status are student-only; confirm is parent-only, so a student can
never confirm their own gate through the API. All three pass `subject=` to the limiter so the bucket
is per-user rather than per-address.

| Route | Handler | Service | Models | Role | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `POST /api/auth/guardian/invite` | `guardian_invite_endpoint` `routes.py:308` | `guardian_invite` `service.py:1268` | `GuardianInviteRequest` `schemas.py:184` → `GuardianInviteResponse` `schemas.py:188` | `student` `routes.py:311` | `guardian_invite` (per user) | §3.1 row `tdd.md:188` |
| `GET /api/auth/guardian/status` | `guardian_status_endpoint` `routes.py:323` | `guardian_status` `service.py:1350` | `GuardianStatusResponse` `schemas.py:211` | `student` `routes.py:325` | `guardian_status` (per user) | §3.1 row `tdd.md:190` |
| `POST /api/auth/guardian/confirm` | `guardian_confirm_endpoint` `routes.py:337` | `guardian_confirm` `service.py:1402` | `GuardianConfirmRequest` `schemas.py:194` → `GuardianConfirmResponse` `schemas.py:200` | `parent` `routes.py:340` | `guardian_confirm` (per user) | §3.1 row `tdd.md:189` |

`guardian_invite` requires the parent's account to **exist** — a missing, inactive or non-parent
account is `422 GUARDIAN_NOT_FOUND` (`service.py:1238-1239`), which the gate screen must render as a
next step rather than a failure. Self-link is checked against the student's **own** email
(`service.py:1222-1233`), not the parent lookup, so the endpoint cannot be used to probe whether an
arbitrary address exists.

`guardian_confirm` returns the link status **before** the transition (`service.py:1349-1352`), so the
three outcomes are distinguishable: zero rows → `400 INVALID_TOKEN`; `verified` → `409
GUARDIAN_ALREADY_LINKED`; `pending` → `200`.

> **Known defect A10 — deferred by the user.** The guardian invitation email is **never sent**.
> `guardian_invite` (`service.py:1210`) issues the token but makes no `_queue_email` call, and
> `guardian_invite_email` (`app/auth/email_templates.py:118`) has **no caller**. The flow is
> therefore unreachable end to end in the current build.
>
> **Known defect C3 — latent because of A10.** `student_name` is interpolated unescaped into that
> template: HTML injection into a parent's inbox from a verified sending domain.
>
> **Known defect D3.** Card 1.6's own failure criterion (`user-stories.md:172`) — "a student
> satisfies their own gate by registering a throwaway parent account" — is satisfiable today.

### 2.6 Outside the router

| Route | Defined at | Auth | Limit | Specified? |
|---|---|---|---|---|
| `GET /health` | `app/main.py:86` | none | none | **not in `tdd.md`** |

> **Known defect D16.** Unauthenticated, unrate-limited, and it reports `settings.environment` in the
> body (`main.py:91`).
>
> **A5 — FIXED, Phase 1 (2026-08-16).** `docs_url` and `redoc_url` gate only the two HTML *viewers*;
> both are pages that fetch `/openapi.json`, which kept its default. Production therefore served the
> complete schema — every route, field name, bound and enum — unauthenticated, while `/docs`
> returned 404 and looked closed. `main.py` now passes
> `openapi_url=None if settings.is_production else "/openapi.json"`.

---

## 3. Dependencies that exist but protect nothing yet

Two RBAC (Role-Based Access Control) dependencies are implemented, tested, and **wired to no route**,
because the routes they were written for are among the 31 missing:

| Dependency | file:line | Waiting on |
|---|---|---|
| `require_subject_scope` | `app/auth/dependencies.py:123` | the classroom and quiz endpoints (§3.5, §3.6) |
| `require_guardian_verified` | `app/auth/dependencies.py:158` | `/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, `/api/reports/*` |

`tdd.md:198` specifies that the gate dependency blocks **every** student learning and assessment
endpoint, and that an authorization-matrix test asserts it on each such route. That test exists
(`backend/tests/integration/test_authz_matrix.py`); the routes do not.

---

## 4. Specified but **not implemented** — all 31

This is the honest build-state record. Each row cites the `tdd.md` line that specifies it. **None of
these paths exists in `backend/app/`** — verified by `grep -rn "@router\." backend/app`, which returns
18 decorators, all listed in §2.

### 4.1 Auth and account management — 5 missing (of 22 in §3.1)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/auth/2fa/backup-codes` | any | Regenerate backup codes, invalidating the old set | `tdd.md:184` |
| 2 | `POST` | `/api/admin/users/{id}/2fa/reset` | Admin | Identity-verified recovery reset; always audited | `tdd.md:185` |
| 3 | `PATCH` | `/api/auth/me` | any | Update own profile and stored `language_pref`, which governs outgoing email (FR-A8) | `tdd.md:192` |
| 4 | `POST` | `/api/auth/password/change` | any | Change password from inside the account; requires the current password (FR-A8) | `tdd.md:193` |
| 5 | `GET` | `/api/auth/2fa/status` | any | Own second-factor method and state; never returns the secret (FR-A8) | `tdd.md:194` |

Rows 3–5 are the FR-A8 account-management gap, finding **E1** in the register. Note the ordering constraint recorded in
the phase plan: the **column grants must be narrowed first** (finding B2/B3), because with today's
table-wide grants and `app_user_self_update` permitting `role`, `PATCH /auth/me` would be a privilege
escalation and password change would have no correct write path.

> **A6 — FIXED, phase 1b (2026-08-16).** Three frontend call sites routed an `admin` account to
> `/admin`, which did not exist, so the account looped on "Redirecting…" for ever. The page is now
> built, and administrators sign in at `POST /api/auth/admin/login` through an unlisted path rather
> than the public form (FR-A2a).
>
> **The surface is still a shell**, and that is the honest state: none of the eight `/api/admin/*`
> endpoints in §3.1 and §7.2 exists, so the dashboard names its five FR-K1 duties and says plainly
> that each is not available yet — the same rule the teacher and parent dashboards follow. What is
> real is the role boundary and the segregated authentication, which are the parts with security
> consequences. Row 2 below is still missing.

### 4.2 Tutor — 3 missing (§3.2, incorporated into §7.2)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 6 | `POST` | `/api/tutor/ask` | Student (gate-verified) | Text or voice question → streamed grounded answer over Server-Sent Events | `tdd.md:239` |
| 7 | `POST` | `/api/tutor/explain-step` | Student | Expand a specific solution step (FR-1) | `tdd.md:240` |
| 8 | `GET` | `/api/tutor/sessions/{id}` | Student (owner) | Retrieve own chat session | `tdd.md:241` |

The agent package these would live in (`backend/app/agent/`, `tdd.md` §3.2) does not exist, and
`ml/` is scaffolded with no implementation.

### 4.3 Quiz and practice — 6 missing (§3.5)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 9 | `POST` | `/api/quiz` | Teacher (subject-scoped) | Create a quiz; optional agent draft | `tdd.md:299` |
| 10 | `POST` | `/api/quiz/{id}/publish` | Teacher | Open a time-boxed window | `tdd.md:300` |
| 11 | `POST` | `/api/quiz/{id}/attempts` | Student (enrolled) | Start an attempt; the server issues shuffled items | `tdd.md:301` |
| 12 | `POST` | `/api/quiz/attempts/{id}/answer` | Student (owner) | Submit an answer; the key is checked server-side | `tdd.md:302` |
| 13 | `POST` | `/api/quiz/attempts/{id}/submit` | Student (owner) | Submit or auto-submit → grade | `tdd.md:303` |
| 14 | `GET` | `/api/practice/adaptive` | Student | Adaptive practice from high-frequency SLOs (Student Learning Outcomes) | `tdd.md:304` |

Relevant database findings, since these are the routes that would first exercise them: **B12**
(`quiz_question` has `SELECT` only, so the authoring path has no write policy at all), **B8**
(`quiz_teacher_write` checks only `created_by`, never the space or the role) and **B7** (the attempt
and mastery policies are `FOR ALL`, so every number a parent or teacher reads is student-writable).
Implementing §3.5 against today's policies would land straight on all three.

### 4.4 Spaces and classroom — 6 missing (§3.6)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 15 | `POST` | `/api/spaces` | Teacher / Parent | Create a space; a teacher declares the subject | `tdd.md:321` |
| 16 | `POST` | `/api/spaces/{id}/join-code` | Owner | Generate, rotate or revoke a join code | `tdd.md:322` |
| 17 | `POST` | `/api/spaces/join` | Student | Join via code, with consent | `tdd.md:323` |
| 18 | `DELETE` | `/api/spaces/{id}/membership` | Student | Leave a space at any time | `tdd.md:324` |
| 19 | `GET` | `/api/spaces/{id}/report` | Teacher (subject) / Parent (child) | Scoped weak-area report | `tdd.md:325` |
| 20 | `POST` | `/api/spaces/{id}/announcements` | Owner | Post a one-way announcement | `tdd.md:326` |

Findings **B9**, **B10** and **B11** all bear on this group: `enrollment_student_join` self-enrols
into *any* space and `enrollment_leave` has no `WITH CHECK`; `classroom_space` has no role check, so
any user can create a space as `owner_role='teacher'`; and `teacher_subject_scope` governs only two
policies, while every other teacher read uses `owns_space()`, which has no scope check.

### 4.5 Reports, administration and subscription — 11 missing (§7.2's own rows)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 21 | `GET` | `/api/reports/weekly` | Student (own) / Parent (child) | Weekly coverage and performance (FR-4) | `tdd.md:1032` |
| 22 | `GET` | `/api/reports/exam-readiness` | Student / Parent | Readiness plus study-next (FR-16) | `tdd.md:1033` |
| 23 | `GET` | `/api/admin/curriculum` | Admin | Knowledge-Base versions and provenance status | `tdd.md:1034` |
| 24 | `POST` | `/api/admin/curriculum/ingest` | Admin | Trigger a provenance-checked ingest (FR-12) | `tdd.md:1035` |
| 25 | `GET` | `/api/admin/security/sbom` | Admin | Agent SBOM (Software Bill of Materials) inventory (FR-13) | `tdd.md:1036` |
| 26 | `POST` | `/api/admin/security/skills/{id}/vet` | Admin | Re-run vetting; admit or block | `tdd.md:1037` |
| 27 | `GET` | `/api/admin/rate-limits` | Admin | View quotas (FR-14) | `tdd.md:1038` |
| 28 | `PUT` | `/api/admin/rate-limits` | Admin | Configure quotas (FR-14) | `tdd.md:1038` |
| 29 | `GET` | `/api/admin/logs/endpoints?date=YYYY-MM-DD` | Admin | Per-day endpoint call logs plus daily counts, error rate and 95th percentile | `tdd.md:1039` |
| 30 | `GET` | `/api/subscription` | Student | Current plan, `status`, `trial_ends_at`, `current_period_end` (FR-A5) | `tdd.md:1040` |
| 31 | `POST` | `/api/subscription/select` | Student | Choose the plan; clears `plan_selection_pending` once the subscription is active | `tdd.md:1041` |

Three notes on this group:

- **Rows 30 and 31 have no owner.** `backend/README.md:115-117` records it: "`GET /subscription` and
  `POST /subscription/select` are specified in `tdd.md` §7 and currently have **no owner**." They are
  also the only two routes that can clear `plan_selection_pending`, which means **the last step of
  onboarding has no implementation** — a student who verifies email, enrols a second factor and
  clears the guardian gate reaches `plan_selection_pending` and stops there once the trial lapses.
- **Row 29 reads a forgeable table.** Finding **B15**: `reqlog_insert` is `WITH CHECK (true)`, so any
  bound user can write rows into the operational log this endpoint would display.
- **Rate limiting is not currently configurable at all** (rows 27–28). The limits are module-level
  constants in `app/core/ratelimit.py:39-75`, and the store is in-process, so a configuration
  endpoint would need the Redis move first.

### 4.6 The error codes with no producer

Two codes in the `tdd.md` §7.3 catalogue (`tdd.md:1047-1067`) have **no factory** in
`app/core/errors.py` and no call site, because the features that raise them do not exist:

| Code | HTTP | Would be raised by |
|---|---|---|
| `SUBSCRIPTION_REQUIRED` | 403 | `/api/subscription*` and the paid-access gate (rows 30–31) |
| `ATTEMPT_EXISTS` | 409 | `/api/quiz/{id}/attempts` (row 11) |
| `NOT_GROUNDED` | 422 | `/api/tutor/ask` (row 6) |
| `MODEL_UNAVAILABLE` | 503 | the agent fallback path (§3.2) |

The sixteen codes that **do** have factories are listed in
[architecture.md §9.2](architecture.md#92-the-error-envelope--appcoreerrorspy).

---

## 5. Conventions every implemented route follows

- **Base path `/api`**, JSON bodies, JWT bearer for sessions (`app/main.py:84`).
- **One error envelope**, always: `{"error": {"code", "message", "details"}}` (`app/core/errors.py:109`).
  **No endpoint invents a code** (`tdd.md:1073`); the one place that was tempted answers
  `400 VALIDATION_ERROR` with `details.fields` instead (`service.py:1057-1065`).
- **Short-lived tokens travel in the body**, sessions in the `Authorization` header (`tdd.md:227`).
- **`X-Request-ID` on every response** (`app/main.py:76`), and in the body of any 500
  (`app/core/errors.py:152`) so a bug report can be tied to a log line.
- **Rate limiting is opt-in per handler**, called as the first statement. Note that `logout` and
  `me` — the two authenticated routes outside the guardian group — have **no** `enforce(...)` call
  (`routes.py:157`, `routes.py:165`).
- **Every response model is explicit.** No handler returns a bare `dict`; the response model is what
  strips `refresh_token` out of the 2FA and refresh responses.

> **Known defect D13.** `onboarding_state` is a five-member `Literal` on `MeResponse`
> (`schemas.py:228-234`) and a plain `str` on the four other responses that carry it —
> `RegisterResponse` (`schemas.py:101`), `TwoFactorConfirmResponse` (`schemas.py:278`),
> `TwoFactorVerifyResponse` (`schemas.py:296`) and `EmailVerifyResponse` (`schemas.py:317`). Only one
> of the five is validated against the state set.

---

## 6. Verifying this document

```bash
# route count
grep -c "^@router\." backend/app/auth/routes.py            # 17

# every route decorator, with its path and line
grep -n "^@router\." backend/app/auth/routes.py

# confirm there is no second router
grep -rn "APIRouter(" backend/app --include=*.py           # 1

# the specified surface
grep -n "^| \(GET\|POST\|PUT\|PATCH\|DELETE\) " tdd.md     # 47 rows; :1038 is two endpoints -> 48
```

---

*Snapshot 2026-08-15. Implemented and specified are kept deliberately distinct: 18 of 49. Known
defects are recorded here rather than deferred until fixed — see the Phase 0 findings register for
the full 35.*
