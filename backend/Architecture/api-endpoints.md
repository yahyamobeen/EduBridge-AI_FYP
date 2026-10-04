# Backend API Endpoints

> Every route the backend actually serves, mapped to its handler, its service function and its row in
> `tdd.md` — followed by the **35 routes that `tdd.md` specifies and this repository does not
> implement.** This document doubles as the honest build-state record.
>
> **Snapshot: 2026-08-15.** Every `file:line` was opened and verified against this snapshot. Line
> numbers drift; when they do, the fix is to re-verify, not to delete the citation.

Related documents: [architecture.md](architecture.md) · [architecture.html](architecture.html) ·
[Database](database.html) · [`tdd.md`](../../tdd.md) · [`prd.md`](../../prd.md) ·
`user-stories.md` (outside the repository, in `Desktop\EduBridge-AI_FYP-planning\`)

**Acronyms.** API — Application Programming Interface. RLS — Row-Level Security. RBAC — Role-Based
Access Control. JWT — JSON Web Token. TOTP — Time-based One-Time Password. OTP — One-Time Password.
SLO — Student Learning Outcome. SBOM — Software Bill of Materials. KB — Knowledge Base.

---

## 1. The count, and where it comes from

| | Count | How it was measured |
|---|---|---|
| Implemented routes | **48** (21 auth + 27 classroom) | `grep -c "^@router\." backend/app/auth/routes.py backend/app/classroom/routes.py` |
| Routers in the backend | **2** | `grep -rn "APIRouter(" backend/app --include=*.py \| wc -l` — `app/auth/routes.py:90`, `app/classroom/routes.py:57` |
| Specified in `tdd.md` §3.1 | 23 | rows at `tdd.md:173-195` — `POST /api/auth/admin/login` was added to the table in phase 1b (FR-A2a) |
| Specified in `tdd.md` §7.2 | 60 | §7.2 consolidates §3.1 plus Tutor (§3.2), Quiz/Practice (§3.5), Spaces/Classroom (§3.6, `tdd.md:325-354` — **40 endpoints** since v0.4.0, counting each method/path pair in a combined row) and its own rows — where `GET /api/admin/rate-limits / PUT` is **two** endpoints |
| **Total specified** | **83** | 23 + 3 + 6 + 40 + 11 (was 49 before `tdd.md` v0.4.0 grew §3.6 from 6 to 40) |
| **Specified but missing** | **35** | 83 − 48 — enumerated in §4 below. Phase 3 built the three FR-A8 account-management routes (finding **E1**); phase 1b before it added one specified endpoint AND implemented it in the same change, leaving the total unchanged. Classroom Phase 1 (2026-10-04) added 34 specified endpoints and built none; **classroom Phase 2 built 10 of the 40, Phase 3 built 4, Phase 4 built 12 and Phase 5 built 1** (§2.8) |

**Two routers.** `backend/app/auth/routes.py` (21 routes) and, since classroom Phase 2,
`backend/app/classroom/routes.py` (27 routes, §2.8). `GET /health` (`backend/app/main.py:119`) is
defined on the application object rather than a router, sits outside `/api`, and is not one of the
83 — `tdd.md` does not specify it.

Both routers are mounted under `settings.api_base_path`, default `/api` (`app/main.py:116-117`).

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

> **A10 — CLOSED** (KAN-21, merged 2026-08-17). `guardian_invite` (`service.py:1539`) builds the
> confirm URL, renders `guardian_invite_email` (`app/auth/email_templates.py:183`) and queues it to
> the parent through `send_after_commit`, so the message is released only if the transaction that
> minted the token commits. The flow is reachable end to end and **the Class 9–10 journey is no
> longer blocked**. Covered by `test_guardian_flow.py`, which captures at the provider seam rather
> than by replacing `_queue_email` — a stub there defines the signature it is testing against, which
> is how a 500 once shipped with a green test.
>
> **C3 — CLOSED in the same change**, because wiring A10 is what made it reachable. `student_name` is
> `app_user.full_name`: length-bounded, character-unrestricted, and editable at any time through
> `PATCH /auth/me`. Escaping is structural — `_wrap` escapes the document title, the body escapes
> text content, and the subject **header** is flattened instead (a newline there forges a header;
> an HTML entity there is just noise a parent has to read). `tests/unit/test_email_template_escaping.py`.
>
> **Known defect D3 — STILL OPEN.** Closing A10 does not close it. Card 1.6's own failure criterion
> (`user-stories.md:172`) — "a student satisfies their own gate by registering a throwaway parent
> account" — remains satisfiable: the student supplies the address, and nothing checks that the
> account on the other end is a real guardian.

### 2.7 FR-A8 — manage own account

Built in Phase 3 (2026-08-16), closing finding **E1**. All three are authenticated, open to **all
four roles**, and keyed on the **acting user** rather than the address — a shared school lab or
carrier NAT would otherwise make one student spend the whole building's allowance.

| Route | Handler | Service | Models | Auth | Limit | `tdd.md` |
|---|---|---|---|---|---|---|
| `PATCH /api/auth/me` | `me_update_endpoint` `routes.py:194` | `update_me` `service.py:678` | `MeUpdateRequest` `schemas.py:361` → `MeResponse` `schemas.py:222` | `authenticated` | `me_update` (30 / 5 min) | §3.1 row `tdd.md:193` |
| `POST /api/auth/password/change` | `password_change_endpoint` `routes.py:213` | `change_password` `service.py:611` | `PasswordChangeRequest` `schemas.py:348` → — (204) | `authenticated` | `password_change` (5 / 5 min) | §3.1 row `tdd.md:194` |
| `GET /api/auth/2fa/status` | `two_factor_status_endpoint` `routes.py:238` | `two_factor_status` `service.py:711` | `TwoFactorStatusResponse` `schemas.py:394` | `authenticated` | `2fa_status` (60 / min) | §3.1 row `tdd.md:195` |

**`PATCH /auth/me` writes `full_name` and `language_pref`, and nothing else can be written.** The
request model has no other field, *and* `app_backend` holds `UPDATE` on exactly those two columns of
`app_user` — so a future model that grew a `class_level` field would be refused by PostgreSQL rather
than silently permitted. `class_level` is the parental-consent gate input (finding **B4**), and
`board` / `student_group` scope every progress record a student has.

It returns a whole `MeResponse` by delegating to `me()` (`service.py`), so the PATCH and GET shapes
cannot drift into describing one account two ways.

**`POST /auth/password/change` goes through `app.change_password`** (`20260816210000`), not a plain
`UPDATE` — `20260816160000` revoked table-wide `UPDATE` on `app_user` precisely so a password write
would have to pass through something that also ends every session.

> ⚠️ **The function takes NO user identifier.** Its subject is `app.current_user_id()`, which
> `authenticated` bound. The plan called for `change_password(p_user_id, p_new_hash)` guarded by
> `p_user_id = app.current_user_id()`; that is the shape of finding **C1** with a check bolted on,
> and a check can be dropped by a later edit that reads like a simplification. Removing the
> parameter makes the whole class unreachable here.
>
> ⚠️ **It returns `(changed boolean, tokens_revoked integer)`, and one field could not do the job.**
> `0` sessions revoked is a legitimate success for a user with none live, so the count cannot also
> signal refusal — a caller writing the natural `if not result:` would report 204 on a password that
> never changed.

**A wrong CURRENT password is `401 UNAUTHENTICATED`**, per `tdd.md` §7.3, which makes that code
"also the only response meaning 'wrong password'" and forbids inventing one. ⚠️ That makes this the
**only** route where both meanings of that 401 are live at once, so a client must opt it out of
refresh-and-retry — see the note added to §7.3.

**Reading `password_hash` for the argon2 comparison needs no privileged path.** `20260816160000`
revoked `UPDATE`, never `SELECT`, so `app_user_self_read` still serves it to the bound user. The
comparison stays in Python, where argon2 lives.

**`GET /auth/2fa/status` is one `SELECT` against `two_factor_status_v`**, a view that existed unused
from the initial schema until `20260816150000` gave it `security_invoker = true` (finding **B1**).
Before that it ran as its owner and returned every account's second-factor state to any caller —
measured at the time as 7 of 7 rows readable, now 0.

> It never returns the secret, and that is **structural rather than a field this response happens to
> omit**: the view was built without `totp_secret_encrypted` or `last_used_counter`. Deliberately
> NOT `app.get_unused_backup_codes`, which returns the backup-code **hashes** — the verify path
> needs those because argon2 is non-deterministic; a status endpoint has no business reading them.
> Deliberately NOT folded into `GET /auth/me` either: one extra round trip on a screen the user
> visits occasionally, rather than a join on the dashboard's hot path.

Pinned by `tests/integration/test_account_management.py` (27 tests), including that a second account
cannot see the first's enrolment, that a refusal writes nothing and ends no session, and that a
teacher's chosen language reaches `app.lookup_user_for_email_flow` — asserted through the function
production actually calls, not through the ORM.

### 2.6 Outside the router

| Route | Defined at | Auth | Limit | Specified? |
|---|---|---|---|---|
| `GET /health` | `app/main.py:119` | none | none | **not in `tdd.md`** |

> **Known defect D16.** Unauthenticated, unrate-limited, and it reports `settings.environment` in the
> body (`main.py:124`).
>
> **A5 — FIXED, Phase 1 (2026-08-16).** `docs_url` and `redoc_url` gate only the two HTML *viewers*;
> both are pages that fetch `/openapi.json`, which kept its default. Production therefore served the
> complete schema — every route, field name, bound and enum — unauthenticated, while `/docs`
> returned 404 and looked closed. `main.py` now passes
> `openapi_url=None if settings.is_production else "/openapi.json"`.

### 2.8 Classroom — `app/classroom/routes.py` (classroom Phases 2–5, 2026-10-04)

The second router, `APIRouter(tags=["classroom"])` at `routes.py:57`, mounted at `main.py:117`.
Every route is one rate-limit call and one service call; **who** may call is the dependency, and
**which classroom** they may touch is decided by the database (`app.*` functions from
`20261004120100` — see [database.md](database.md#classroom--post-apispaces-functions)). An unknown
id and a forbidden id get the same byte-identical `403 FORBIDDEN_SCOPE`.

Guards (`app/classroom/dependencies.py`): **Participant** = `require_guardian_verified` then
teacher-or-student (`:22`); **GatedStudent** = `require_guardian_verified` then student (`:35`);
**Teacher** = `require_role('teacher')`; **AnyStudent** = `require_role('student')` — leaving is a
consent right and is deliberately **not** guardian-gated.

| Method | Path | Handler | Guard | Bucket | Service | `tdd.md` |
|---|---|---|---|---|---|---|
| `POST` | `/api/spaces/join` | `routes.py:73` | GatedStudent | `classroom_join` | `service.join_space` `:230` | `:330` |
| `GET` | `/api/spaces` | `routes.py:80` | Participant | `classroom_read` | `service.list_spaces` `:104` | `:326` |
| `POST` | `/api/spaces` | `routes.py:86` | Teacher | `classroom_write` | `service.create_space` `:148` | `:325` |
| `GET` | `/api/spaces/{space_id}` | `routes.py:94` | Participant | `classroom_read` | `service.get_space` `:113` | `:327` |
| `PATCH` | `/api/spaces/{space_id}` | `routes.py:100` | Teacher | `classroom_write` | `service.update_space` `:176` | `:328` |
| `POST` | `/api/spaces/{space_id}/join-code` | `routes.py:108` | Teacher | `classroom_write` | `service.change_join_code` `:213` | `:329` |
| `DELETE` | `/api/spaces/{space_id}/membership` | `routes.py:118` | AnyStudent | `classroom_write` | `service.leave_space` `:270` | `:331` |
| `GET` | `/api/spaces/{space_id}/people` | `routes.py:124` | Participant | `classroom_read` | `service.people` `:276` | `:332` |
| `DELETE` | `/api/spaces/{space_id}/members/{student_id}` | `routes.py:130` | Teacher | `classroom_write` | `service.remove_student` `:302` | `:333` |
| `GET` | `/api/reference/subjects` | `routes.py:138` | `authenticated` | `classroom_read` | `service.list_subjects` `:316` | `:334` |
| `GET` | `/api/spaces/{space_id}/announcements` | `routes.py:155` | Participant | `classroom_read` | `announcements.list_announcements` `:47` | `:335` |
| `POST` | `/api/spaces/{space_id}/announcements` | `routes.py:166` | Teacher | `classroom_write` | `announcements.create_announcement` `:73` | `:336` |
| `PATCH` | `/api/announcements/{announcement_id}` | `routes.py:180` | Teacher | `classroom_write` | `announcements.update_announcement` `:94` | `:337` |
| `DELETE` | `/api/announcements/{announcement_id}` | `routes.py:188` | Teacher | `classroom_write` | `announcements.delete_announcement` `:144` | `:337` |
| `GET` | `/api/spaces/{space_id}/assignments` | `routes.py:197` | Participant | `classroom_read` | `assignments.list_assignments` `:121` | `:338` |
| `POST` | `/api/spaces/{space_id}/assignments` | `routes.py:210` | Teacher | `classroom_write` | `assignments.create_assignment` `:209` | `:338` |
| `GET` | `/api/assignments/{assignment_id}` | `routes.py:224` | Participant | `classroom_read` | `assignments.get_assignment` `:145` | `:339` |
| `PATCH` | `/api/assignments/{assignment_id}` | `routes.py:232` | Teacher | `classroom_write` | `assignments.update_assignment` `:240` | `:339` |
| `DELETE` | `/api/assignments/{assignment_id}` | `routes.py:242` | Teacher | `classroom_write` | `assignments.delete_assignment` `:296` | `:339` |
| `PUT` | `/api/assignments/{assignment_id}/submission` | `routes.py:248` | GatedStudent | `classroom_write` | `assignments.save_draft` `:348` | `:340` |
| `POST` | `/api/assignments/{assignment_id}/submission/turn-in` | `routes.py:256` | GatedStudent | `classroom_write` | `assignments.turn_in` `:360` | `:341` |
| `POST` | `/api/assignments/{assignment_id}/submission/unsubmit` | `routes.py:262` | GatedStudent | `classroom_write` | `assignments.unsubmit` `:369` | `:341` |
| `GET` | `/api/assignments/{assignment_id}/submissions` | `routes.py:268` | Teacher | `classroom_read` | `assignments.submissions_table` `:422` | `:342` |
| `GET` | `/api/assignments/{assignment_id}/submissions/{student_id}` | `routes.py:276` | Teacher | `classroom_read` | `assignments.student_work` `:435` | `:342` |
| `PUT` | `/api/assignments/{assignment_id}/grades/{student_id}` | `routes.py:284` | Teacher | `classroom_write` | `assignments.save_grade` `:455` | `:343` |
| `GET` | `/api/reference/subjects/{subject_id}/chapters` | `routes.py:298` | Teacher | `classroom_read` | `assignments.list_chapters` `:168` | `:344` |
| `GET` | `/api/calendar?from=&to=` | `routes.py:308` | Participant | `classroom_read` | `calendar.items_between` `:61` | `:345` |

Buckets (`app/core/ratelimit.py:105-107`), all per **user**: `classroom_read` 120/60 s,
`classroom_write` 30/60 s, `classroom_join` **10/300 s** — the one brute-force surface, against a
2⁴⁰ code space.

Responses worth knowing:

- **`POST /spaces/join`** answers `200 {space_id, already_member}`, or `400 VALIDATION_ERROR` with
  `details.reason` ∈ `invalid_code` (also revoked, expired, archived and — deliberately — a
  **removed** student), `class_mismatch` (plus `details.space` so the student can be told which
  class it is for), `classroom_full`; or `403 GATE_PENDING`.
- **`POST /spaces`** answers `201` with the classroom **and its first code** (one transaction:
  `app.create_space` then `app.rotate_join_code`), or `400` with `fields.subject_id` /
  `reason: classroom_limit`.
- **`PATCH /spaces/{id}`** — an empty body is a `400`; **unarchiving** re-checks the 50-active cap in
  the service (`service.py:181-197`), because the column grant would otherwise let a teacher create
  50, archive them, create 50 more and unarchive everything.
- **`DELETE …/membership`** is `204` whether or not the caller was a member, so it cannot probe
  which classrooms exist.
- **`GET /spaces/{id}`** carries `join_code` for a scoped owner only; the **database** returns
  nothing to anyone else (`join_code_owner_read`), not a check in the service.

**The stream (classroom Phase 3).** `app/classroom/announcements.py`, over the policies of
`20261004130000` ([database.md](database.md#classroom), finding **B27**):

- **`GET /spaces/{id}/announcements`** answers `200 {items, next_cursor}`, newest first by
  `(publish_at, id)`, 20 per page (`PAGE_SIZE`, `announcements.py:27`). `?cursor=` is the opaque
  `next_cursor` of the previous page (`app/classroom/pagination.py`: base64 of `publish_at|id`; a
  malformed or timezone-naive cursor is `400` with `fields.cursor`). **Members never receive a
  scheduled post**: Row-Level Security removes it, so the service runs the same query for both
  roles, and `scheduled` is only ever `true` in the owner's view.
- **`POST /spaces/{id}/announcements`** answers `201`. Body 1–5000 characters (trimmed);
  `publish_at` optional and timezone-aware. Omitted means now; otherwise it must be **after the
  database's `now()` and within 365 days**, else `400` with `fields.publish_at`. The comparison uses
  the database clock, not Python's (`check_schedule`, `app/classroom/scheduling.py:28`, shared
  with assignments).
- **`PATCH /announcements/{id}`** takes `body` and/or `publish_at`; empty is `400`. **Only a
  still-scheduled post can be rescheduled** (`400 fields.publish_at` otherwise): pulling a published
  post back into the future would hide what students have already read. This is the one rule the
  database does not express.
- **`DELETE /announcements/{id}`** answers `204` and writes an `audit_log` row
  `classroom.announcement_deleted`. Not the author, an archived classroom, or no such post all
  answer the same `403`.

**Assignments, submissions and grades (classroom Phase 4).** `app/classroom/assignments.py`, over
the tables, policies and functions of `20261004140000`
([database.md](database.md#classroom--assignment-functions)). The same query serves owner and
member; the database narrows it:

- **`GET /spaces/{id}/assignments`** answers `200 {items, next_cursor}` — the stream's keyset
  pagination, 20 per page. A member gets `my_status` (`assigned`, `turned_in`, `turned_in_late`,
  `missing`, `graded`) and `my_grade` (only once returned); the owner gets `turned_in_count`
  (turned-in work of **active** members). Status is **derived** (`app/classroom/status.py`) from
  `turned_in_at`, `due_at` and `returned_at` against the database clock — on the deadline is on
  time, and at the deadline is not yet missing. A member never receives a scheduled assignment.
- **`POST /spaces/{id}/assignments`** answers `201` with the detail. `title` 1–200, `instructions`
  ≤ 10 000, `points` 1–1000 (optional), `due_at` and `publish_at` timezone-aware (optional). Each
  refusal names its field: `publish_at` (past or over a year ahead), `due_at` (not after posting),
  `chapter_id` (not in the classroom's subject — also a composite foreign key in the database).
- **`PATCH /assignments/{id}`** sends **only what changed**; `null` clears `due_at`, `points` or
  `chapter_id`, and is a `400` for anything else. `publish_at` moves only while still scheduled.
  Lowering `points` below an existing grade is `400 fields.points` — the service locks the row
  `FOR UPDATE` before checking, and the update policy refuses it regardless
  (`app.points_compatible`).
- **`DELETE /assignments/{id}`** answers `204`, through `app.delete_assignment` (there is no DELETE
  grant), and writes `classroom.assignment_deleted` to `audit_log`.
- **`PUT …/submission`**, **`POST …/turn-in`**, **`POST …/unsubmit`** each answer `200` with the
  student's own submission. Turning in twice, or unsubmitting work that is not turned in, is not
  an error. A state refusal is `400` with **`details.reason`**: `turned_in` (unsubmit before
  editing) or `graded` (the teacher has saved a grade — returned or not — so the work is locked).
  `link_url` must be a full `https://` link (`400 fields.link_url`).
- **`GET …/submissions`** lists **every active member**, submitted or not; **`GET
  …/submissions/{student_id}`** is one student's work. **A draft is never shown** — `body` and
  `link_url` are `null` until the work is turned in, because the database returns nothing earlier.
- **`PUT …/grades/{student_id}`** saves a grade (`0 ≤ grade ≤ points`, two decimals; `null` =
  feedback only) and private feedback; `return_to_student: true` makes both visible to the student
  and writes `classroom.grade_returned` to `audit_log`. Returning is one-way. Grading a non-member,
  or in an archived classroom, is `403`.
- **`GET /reference/subjects/{id}/chapters`** — the chapter picker, teachers only. Empty until
  chapters are ingested.

**The calendar (classroom Phase 5).** `app/classroom/calendar.py` — no table and no migration of its
own: one query over the Phase 3 and 4 tables, under their policies, so it shows only what the caller
could already see (`prd.md` CL-9).

- **`GET /calendar?from=&to=`** answers `200 {items, truncated}`, ordered by time. `from` and `to`
  are timezone-aware instants, half-open, **at most 62 days apart** (`MAX_RANGE`, `calendar.py:30`)
  — anything else, including a naive time, is `400`. Each item is `{kind, at, space_id,
  space_title, ref_id, title, my_status}`: `due` (an assignment's deadline — for a student with
  their derived `my_status`), or, **for the owner only**, `scheduled_assignment` /
  `scheduled_announcement` on the moment the post goes live (an announcement's `title` is its first
  80 characters, whitespace collapsed). Archived classrooms are left out; a student who left a class
  stops seeing it, as everywhere else. More than 500 entries sets `truncated` (`MAX_ITEMS`, `:31`).

Pinned by `tests/integration/test_classroom_api.py` (29 tests), `test_classroom_stream.py` (15),
`test_classroom_assignments.py` (21) and `test_classroom_calendar.py` (12) over the database suite
`test_classroom_rls.py` (69);
`tests/unit/test_classroom_schemas.py` (30), `test_classroom_pagination.py` (6) and
`test_classroom_status.py` (9) cover the request bounds, the cursor and the status boundaries.

---

## 3. Dependencies that exist but protect nothing yet

Two RBAC (Role-Based Access Control) dependencies were written ahead of their routes. **One is now
wired**; the other still protects nothing:

| Dependency | file:line | Status |
|---|---|---|
| `require_subject_scope` | `app/auth/dependencies.py:206` (since 2026-10-04 it also requires `revoked_at IS NULL`, `:236-242`) | **Still wired to no route.** The classroom routes do not need it — they take a `space_id`, not a `subject_id`, and the space's own scope is checked inside `app.owns_space`. Waits on the subject-report and quiz endpoints (§3.5, §3.6) |
| `require_guardian_verified` | `app/auth/dependencies.py:248` | **Wired since classroom Phase 2**, through `participant` and `gated_student` (`app/classroom/dependencies.py:22`, `:35`) on every student classroom route except leaving (§2.8). Still waits on `/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`, `/api/reports/*` |

`tdd.md:198` specifies that the gate dependency blocks **every** student learning and assessment
endpoint, and that an authorization-matrix test asserts it on each such route. That test exists
(`backend/tests/integration/test_authz_matrix.py`); the routes do not.

---

## 4. Specified but **not implemented** — all 52

This is the honest build-state record. Each row cites the `tdd.md` line that specifies it. **None of
these paths exists in `backend/app/`** — verified by `grep -rn "@router\." backend/app`, which returns
21 decorators, all listed in §2.

### 4.1 Auth and account management — 2 missing (of 22 in §3.1)

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| 1 | `POST` | `/api/auth/2fa/backup-codes` | any | Regenerate backup codes, invalidating the old set | `tdd.md:184` |
| 2 | `POST` | `/api/admin/users/{id}/2fa/reset` | Admin | Identity-verified recovery reset; always audited | `tdd.md:185` |

> **E1 — FIXED, Phase 3 (2026-08-16).** The three FR-A8 account-management routes that used to be
> rows 3–5 here are built and live in [§2.7](#27-fr-a8--manage-own-account). ⚠️ **Their `tdd.md`
> citations in this table were off by one** (192/193/194 for rows that are at 193/194/195) —
> corrected while moving them, because a citation nobody re-opens is how a document stops being
> evidence.
>
> **The ordering constraint this section recorded was real and was honoured.** The column grants had
> to be narrowed first (findings B2/B3, migration `20260816160000`): with table-wide grants and
> `app_user_self_update` permitting `role`, `PATCH /auth/me` would have been a privilege escalation
> and password change would have had no correct write path. Phase 2 closed that, and Phase 3 then
> found the write path had to be a function rather than a grant — `app.change_password`.
>
> **Row 1 is still missing and Phase 3 depends on that being true.** `GET /auth/2fa/status` reports
> `backup_codes_remaining` precisely so the count can be read *without* calling the endpoint that
> replaces every code, which is card 1.3's success criterion (`user-stories.md:93`).

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

### 4.4 Spaces and classroom — 13 missing (§3.6; 27 of 40 built in classroom Phases 2–5)

The six rows `tdd.md` specified through v0.3.9 keep their numbers. **Rows 15–18 were built in
classroom Phase 2 and row 20 in Phase 3**; they are now in §2.8 and stay here, struck through, so
the numbering of every later row is stable:

| # | Method | Path | Role | Purpose | `tdd.md` |
|---|---|---|---|---|---|
| ~~15~~ | `POST` | `/api/spaces` | Teacher | **BUILT** — §2.8 | `tdd.md:325` |
| ~~16~~ | `POST` | `/api/spaces/{id}/join-code` | Owner | **BUILT** — §2.8 | `tdd.md:329` |
| ~~17~~ | `POST` | `/api/spaces/join` | Student (gate-checked) | **BUILT** — §2.8 | `tdd.md:330` |
| ~~18~~ | `DELETE` | `/api/spaces/{id}/membership` | Student (**not** gate-checked) | **BUILT** — §2.8 | `tdd.md:331` |
| 19 | `GET` | `/api/spaces/{id}/report` | Teacher (subject) / Parent (child) | Scoped weak-area report | `tdd.md:354` |
| ~~20~~ | `POST` | `/api/spaces/{id}/announcements` | Owner | **BUILT** — §2.8 | `tdd.md:336` |

**`tdd.md` v0.4.0 added 34 more** (`tdd.md:326-353`), to be built by classroom phase — they are
not numbered here, so that the numbering of every later section stays stable:

| Phase | Endpoints | Count |
|---|---|---|
| 2 — classrooms core | ~~`GET /api/spaces` · `GET`/`PATCH /api/spaces/{id}` · `GET /api/spaces/{id}/people` · `DELETE /api/spaces/{id}/members/{student_id}` · `GET /api/reference/subjects`~~ **BUILT** — §2.8 | 0 of 6 left |
| 3 — stream | ~~`GET /api/spaces/{id}/announcements` · `PATCH`/`DELETE /api/announcements/{id}`~~ **BUILT** — §2.8 | 0 of 3 left |
| 4 — assignments | ~~`GET`/`POST /api/spaces/{id}/assignments` · `GET`/`PATCH`/`DELETE /api/assignments/{id}` · `PUT …/submission` · `POST …/turn-in` · `POST …/unsubmit` · `GET …/submissions` · `GET …/submissions/{student_id}` · `PUT …/grades/{student_id}` · `GET /api/reference/subjects/{id}/chapters`~~ **BUILT** — §2.8 | 0 of 12 left |
| 5 — calendar | ~~`GET /api/calendar`~~ **BUILT** — §2.8 | 0 of 1 left |
| 6 — files | three uploads, two downloads, two deletes | 7 |
| 7 — chat | `GET`/`POST /api/spaces/{id}/messages` · `DELETE /api/messages/{id}` · `PUT …/mute` | 4 |
| 8 — parent | `GET /api/parent/classrooms` | 1 |

**Findings B9, B10 and B11 are FIXED at the database layer** (`20261004120000`,
`20261004120100`, applied 2026-10-04 and re-verified on the live database), *before* any of these
routes existed — the order
`backend/Architecture/database.md` argued for. Previously `enrollment_student_join` self-enrolled
into *any* space, `classroom_space` had no role check, and `owns_space()` had no scope check. The
routes in this group will call the classroom functions catalogued in
[`database.md`](database.md#classroom--post-apispaces-functions); none of them may need a write grant.

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
grep -c "^@router\." backend/app/auth/routes.py backend/app/classroom/routes.py   # 21 and 27

# every route decorator, with its path and line
grep -n "^@router\." backend/app/auth/routes.py backend/app/classroom/routes.py

# the routers — exactly two
grep -rn "APIRouter(" backend/app --include=*.py           # 2

# the specified surface
grep -n "^| \(GET\|POST\|PUT\|PATCH\|DELETE\) " tdd.md     # 72 rows; many combine methods or paths — §1 counts 83 endpoints
```

---

*Snapshot 2026-08-15, counts re-measured 2026-10-04 (classroom Phase 1). Implemented and specified
are kept deliberately distinct: 48 of 83 (classroom Phase 5). Known
defects are recorded here rather than deferred until fixed — see the Phase 0 findings register for
the full 35.*
