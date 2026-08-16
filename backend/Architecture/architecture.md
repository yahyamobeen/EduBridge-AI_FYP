# Backend Architecture

> How the EduBridge AI backend is structured — the layers a request falls through, the two-layer
> authorization model and where it currently fails, the seven token kinds, the onboarding state
> machine and the parental-consent gate.
>
> **Snapshot: 2026-08-15.** Source of truth is the code; every count below records the command that
> produced it. Keep this file in sync per `backend/CLAUDE.md`.

Related documents: [Database](database.html) · [API endpoints](api-endpoints.md) ·
[architecture.html](architecture.html) (the same content with rendered diagrams)

Contract documents at the repository root: [`prd.md`](../../prd.md) · [`tdd.md`](../../tdd.md) ·
[`user-stories.md`](../../user-stories.md)

**Acronyms are expanded on first use in each section.** API — Application Programming Interface.
RLS — Row-Level Security. RBAC — Role-Based Access Control. JWT — JSON Web Token. TOTP —
Time-based One-Time Password. OTP — One-Time Password. TTL — Time To Live. CORS — Cross-Origin
Resource Sharing. ORM — Object-Relational Mapper. SQL — Structured Query Language. GUC — Grand
Unified Configuration (a PostgreSQL runtime setting).

---

## 1. Overview

The backend is a **single FastAPI application** with one router. All server logic lives under
`backend/app/`, split into three packages:

| Package | Contents |
|---|---|
| `app/auth/` | The only router (`routes.py`), the service layer, dependencies, tokens, the gate, the onboarding derivation, email, TOTP, backup codes, Turnstile |
| `app/core/` | Configuration, the database engines and the per-transaction user binding, the error envelope, the rate limiter |
| `app/models/` | SQLAlchemy ORM (Object-Relational Mapper) declarations and the Python enumerations that mirror the PostgreSQL types |

The database is **PostgreSQL on Supabase**, with the schema owned by versioned SQL (Structured Query
Language) migrations in `supabase/migrations/` rather than by the ORM. Authentication is
**application-managed** — Supabase Auth is not used, so `auth.uid()` does not exist and every
Row-Level Security policy reads `app.current_user_id()` instead. The frontend is a separate Next.js
application in the same repository that talks to this backend over HTTP.

### Headline numbers

Every number below is measured, with the command that produced it. All commands are run from the
repository root.

| Metric | Value | Command |
|---|---|---|
| Python source files | **26** | `find backend/app -type f -name "*.py" \| wc -l` |
| Routers | **1** (`app/auth/routes.py:79`) | `grep -rn "APIRouter(" backend/app --include=*.py \| wc -l` |
| Implemented routes | **17** | `grep -c "^@router\." backend/app/auth/routes.py` |
| Routes specified in `tdd.md` §3.1 + §7.2 | **48** | see [api-endpoints.md](api-endpoints.md) for the row-by-row derivation |
| Specified but **not** implemented | **31** | 48 − 17 |
| Applied migrations | **11** | `ls supabase/migrations/*.sql \| wc -l` |
| Test files | **25** (10 unit, 15 integration) | `find backend/tests/unit -name "test_*.py" \| wc -l` · `find backend/tests/integration -name "test_*.py" \| wc -l` |
| `app.*` privileged functions called from Python | **24 distinct, 28 call sites** | `grep -rnE "SELECT (\*\|[a-z_, ]+) FROM app\.\|SELECT app\." backend/app --include=*.py` |

### Directories that are scaffolded, with no implementation

`ml/`, `mcp-servers/`, `infra/` and `backend/app/workers/` are **scaffolded — directory structure
and placeholders only, no implementation**. They contain `.gitkeep` files plus an `.env.example` in
two of them, and nothing else:

```
find ml mcp-servers infra backend/app/workers -type f
  backend/app/workers/.gitkeep
  infra/.env.example
  infra/deploy/.gitkeep
  infra/docker/.gitkeep
  mcp-servers/.env.example
  mcp-servers/ocr/.gitkeep
  mcp-servers/stt/.gitkeep
  mcp-servers/translation/.gitkeep
  mcp-servers/tts_avatar/.gitkeep
  mcp-servers/web_search/.gitkeep
  ml/eval/.gitkeep
  ml/serving/.gitkeep
```

This matters for reading `tdd.md`: §3.3 (Skills and MCP — Model Context Protocol), §3.8 (the
curriculum pipeline) and §2.2's machine-learning serving stack describe systems whose directories
exist and whose code does not.

---

## 2. The layers

A request falls through seven layers. Nothing skips a layer, and the order is load-bearing at three
points: the rate limiter runs before any password hash; the `authenticated` dependency binds the
user before it reads the user's own row; and the transaction that carries the binding is the one the
service code runs inside.

```
HTTP request
  │
  1  CORSMiddleware                       main.py:61
  2  request_context middleware           main.py:69   → X-Request-ID and three security headers
  3  route function                       auth/routes.py
  4  enforce(...) rate limiter            core/ratelimit.py:117
  5  authenticated dependency             auth/dependencies.py:29   → binds app.current_user_id
  6  service function                     auth/service.py
  7  SQLAlchemy Core text()               → PostgreSQL under Row-Level Security
```

### 2.1 CORS (Cross-Origin Resource Sharing) — `app/main.py:61`

`allow_origins` comes from `settings.cors_origins` and `allow_credentials=True`. The comment at
`main.py:57-60` records why a wildcard is refused: with credentials enabled Starlette does **not**
send a literal `*`, it echoes the requesting origin back, so a wildcard would let any site make
credentialed calls — and the refresh cookie is a credential. `Settings._production_is_actually_hardened`
(`core/config.py:159`) raises at startup if `"*"` appears in `cors_origins` while the environment is
production.

> **Known defect D4 (findings register).** A 500 response bypasses CORS and every security header.
> The exception handler at `core/errors.py:138` returns its `JSONResponse` from inside the
> middleware stack in a way that does not re-enter the CORS layer, so a browser sees an opaque
> network failure rather than the `INTERNAL_ERROR` envelope. Recorded here, fixed in a later phase.

### 2.2 Request-context middleware — `app/main.py:69`

One `uuid4` per request, stored on `request.state.request_id`, echoed as `X-Request-ID`, and
attached to the body of any 500 (`core/errors.py:152`). It also sets `X-Content-Type-Options:
nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` on every response.

> **Known defects D15 and E3.** There is no `Cache-Control: no-store` on token-bearing responses,
> and no HSTS (HTTP Strict Transport Security) header. Neither is set anywhere in `main.py`.

### 2.3 Route — `app/auth/routes.py`

The single router is created at `routes.py:79` and mounted at `settings.api_base_path` (default
`/api`) by `main.py:84`. Handlers are thin: they enforce a rate limit, call one service function,
and shape the response model. The only route logic that is not a pass-through is the refresh-cookie
write, which appears in three handlers (`routes.py:119`, `routes.py:188`, `routes.py:220`).

A standing note sits at the top of the file (`routes.py:81-85`): **no route depends on
`get_service_db`.** See §4.

`GET /health` is defined on the application rather than the router (`main.py:86`), so it sits
outside `/api` and outside the rate limiter.

> **Known defect D16.** `/health` is unauthenticated, unrate-limited, and reports
> `settings.environment` in its body (`main.py:91`).

### 2.4 Rate limiter — `app/core/ratelimit.py:117`

`enforce(request, bucket=..., limit=..., subject=...)` is called as the first statement of every
rate-limited handler. It is an **in-process fixed-window counter** over a module-level dictionary
guarded by a `threading.Lock` (`ratelimit.py:77-78`). Its own module docstring states the limit of
that design, and it is quoted here rather than paraphrased:

> "SCOPE, STATED PLAINLY: this is an IN-PROCESS fixed-window counter. It is a real control for a
> single-process deployment and it is NOT sufficient for several workers or several instances,
> because each keeps its own counters — N workers means N times the allowance. `REDIS_URL` is
> already in the environment template for exactly this reason; moving the store there is the
> upgrade, and the interface here does not change when it happens."
> — `backend/app/core/ratelimit.py:9-14`

Two keying strategies (`ratelimit.py:81`):

- **Pre-authentication** buckets (`register`, `login`, `refresh`) key on `request.client.host`. The
  comment at `ratelimit.py:93-96` records that behind a proxy this is the proxy's address, and that
  `X-Forwarded-For` is deliberately **not** trusted because any caller can set it.
- **Authenticated** buckets pass `subject=str(ctx.user_id)` so the bucket is per-user. The reason is
  the deployment target: a Pakistani school laboratory or a mobile carrier puts a whole cohort
  behind one public address, so an address-keyed limit on the guardian-status poll would let fifteen
  students exhaust the allowance for the building (`ratelimit.py:82-90`).

A second, per-account layer exists for the 2FA (two-factor authentication) endpoints. The address
ceilings are deliberately loose and the real bound is `enforce_subject` (`ratelimit.py:127`), called
from inside the service once a token has identified whose account it is
(`service.py:720`, `:802`, `:923`, `:1042`).

| Bucket | Address limit | Per-account limit | Defined at |
|---|---|---|---|
| `login` | 10 / 60 s | — | `ratelimit.py:39` |
| `register` | 5 / 300 s | — | `ratelimit.py:40` |
| `refresh` | 30 / 60 s | — | `ratelimit.py:41` |
| `guardian_status` | 60 / 60 s (per user) | — | `ratelimit.py:47` |
| `guardian_invite` | 5 / 300 s (per user) | — | `ratelimit.py:48` |
| `guardian_confirm` | 10 / 60 s (per user) | — | `ratelimit.py:49` |
| `2fa_enroll` | 60 / 300 s | 5 / 300 s | `ratelimit.py:61`, `:72` |
| `2fa_confirm` | 100 / 300 s | 5 / 300 s | `ratelimit.py:62`, `:73` |
| `2fa_verify` | 200 / 300 s | 10 / 300 s | `ratelimit.py:63`, `:74` |
| `2fa_resend` | 60 / 300 s | 3 / 300 s | `ratelimit.py:64`, `:75` |
| `email_verify` | 100 / 300 s | — | `ratelimit.py:65` |
| `email_resend` | 30 / 300 s | — | `ratelimit.py:66` |
| `password_forgot` | 30 / 300 s | — | `ratelimit.py:67` |
| `password_reset` | 60 / 300 s | — | `ratelimit.py:68` |

`rate_limited_with_retry` (`ratelimit.py:135`) puts a real `retry_after` into `details` so the
client's countdown is honest.

> **Known defect E3.** `Retry-After` is placed in the JSON body's `details`, not in the HTTP
> `Retry-After` header that `tdd.md` §7.3 specifies.

### 2.5 The `authenticated` dependency — `app/auth/dependencies.py:29`

The single dependency for every authenticated route. In order:

1. Read the bearer credentials (`HTTPBearer(auto_error=False)`, `dependencies.py:17`). Missing
   credentials raise `UNAUTHENTICATED` (`dependencies.py:54-55`).
2. `decode_access_token` (`auth/security.py:92`) verifies the JWT signature and requires
   `type == "access"`. A failure is the same message as a missing token, deliberately.
3. Open a session, then **bind first, read second** (`dependencies.py:66`):
   `set_current_user_id(session, user_id)`.
4. Read `status, role FROM app_user WHERE id = :uid AND deleted_at IS NULL`
   (`dependencies.py:68-75`). This read runs **under** Row-Level Security: the policy
   `app_user_self_read` is `USING (id = app.current_user_id())`, which is satisfied by step 3, so
   the identity check needs no privileged connection at all.
5. Yield `AuthContext(session, user_id, role)` (`dependencies.py:20`, `:82`), then commit; roll back
   on any exception.

The docstring at `dependencies.py:42-52` records what this replaced: a design that resolved the
token against an RLS-bypassing service session, and passed the user id to the session factory
through `request.state` — which made correctness depend on FastAPI resolving two parameters in
declaration order.

Three dependencies wrap it (`dependencies.py:98-105`), none of which opens a privileged connection:

| Dependency | File:line | Purpose | Used by |
|---|---|---|---|
| `require_role(*roles)` | `dependencies.py:108` | Role gate; raises 403 `FORBIDDEN_SCOPE` | the three guardian routes |
| `require_subject_scope` | `dependencies.py:123` | Teacher must hold a `teacher_subject_scope` row for the path's `{subject_id}` | **no route yet** — exported for the classroom endpoints |
| `require_guardian_verified` | `dependencies.py:158` | The parental-consent gate | **no route yet** — the learning endpoints it protects do not exist |

`require_subject_scope` carries a long comment (`dependencies.py:134-147`) explaining that it must
be used as `Depends(require_subject_scope)` on a route declaring `{subject_id}` in its path, because
the factory form it replaced could never see a per-request path parameter.

### 2.6 Service layer — `app/auth/service.py`

One module, 26 functions, no classes. Every route's business logic lives here and every function
takes the `Session` as its first argument. The service layer is where the transaction-safety rules
are enforced, and two of them are explicit commits inside an otherwise commit-free request:

- `refresh()` commits **before** raising after a token-reuse detection (`service.py:386`), because
  the 401 would otherwise unwind through `get_db`'s rollback and undo the family revocation.
- `_record_2fa_failure()` commits (`service.py:685`) for the same reason: a lockout written and not
  committed is a lockout that never happened.

Both are deliberate exceptions to the rule in §3.1 that a stray `commit()` unbinds the user.

### 2.7 SQLAlchemy Core `text()` → PostgreSQL

Queries are written as SQL strings passed to `sqlalchemy.text()` with **bound parameters**, not ORM
queries. The ORM declarations in `app/models/` exist for the few statements that use them
(`revoke_user_tokens` at `auth/tokens.py:150` is the only ORM write in the request path) and as
documentation of the schema; the schema itself is owned by the migrations.

There is **no SQL string interpolation anywhere** — this was checked across the whole backend during
the Epic 1 review and recorded as verified-correct in the findings register.

---

## 3. The two-layer authorization model — and its current failure

### 3.1 How the binding works

Because authentication is application-managed, there is no `auth.uid()`. Every Row-Level Security
policy reads `app.current_user_id()`, which resolves a transaction-scoped PostgreSQL setting the
application writes:

```python
session.execute(
    text("SELECT set_config('app.current_user_id', :uid, true)"),
    {"uid": str(parsed)},
)
```
— `app/core/db.py:56-59`

Three properties are load-bearing, and all three are documented in `set_current_user_id`'s own
docstring (`core/db.py:33-54`):

1. **`is_local => true`** is the parameterised equivalent of `SET LOCAL`, which cannot take a bind
   parameter. This is the safe form every other module copies.
2. **It is scoped to the transaction.** A `commit()` in the middle of a request ends that
   transaction and silently discards the setting. Every query afterwards on that session runs with
   no user bound and returns zero rows, with **no error raised anywhere**.
3. **It is never called with `None`.** "Unset" is the fail-closed default and stays reachable only
   by not calling the function at all.

Three sessions exist:

| Factory | File:line | User bound? | Used by |
|---|---|---|---|
| `get_db` | `core/db.py:62` | No — every owner-scoped policy denies | unauthenticated routes; `register` binds the id it is about to create (`service.py:120`) |
| `authenticated` | `auth/dependencies.py:29` | Yes, from the verified token | every authenticated route |
| `get_service_db` | `core/db.py:86` | **Bypasses RLS entirely** | background jobs only — **no route depends on it** (`routes.py:81-85`) |

The application **refuses to start** if its own connection can bypass Row-Level Security.
`assert_backend_role_cannot_bypass_rls` (`core/db.py:119`) queries `rolsuper, rolbypassrls FROM
pg_roles WHERE rolname = current_user` and raises `UnsafeDatabaseRoleError` (`core/db.py:103`) if
either is true. Being unable to *check* is also a refusal, reported separately as
`DatabaseUnreachableError` (`core/db.py:107`) — the two mean opposite things and need different
responses from whoever reads the log. The check is wired into the lifespan at `main.py:37`.

### 3.2 What Card 1.5 promises

`user-stories.md:134-135` states the promise:

> "As a security administrator, I want each request checked by the application and again by the
> database, so that a single missed check can never expose another student's data."

Its success criterion (`user-stories.md:143`) is that "Row-Level Security operates as a second
independent layer beneath application authorization, neither relied upon alone."

### 3.3 The database layer does not currently hold

**State this plainly: the second layer would not catch a missed application check.** The Epic 1
database sweep produced nineteen findings (B1–B19 in the findings register) that together mean the
application layer is holding alone. The full policy catalogue, with the `USING` and `WITH CHECK`
clause of every policy, is on the **[database page](database.html)** — that is where these findings
are recorded in detail. The summary a reader of *this* page needs:

| # | Finding | Effect on the second layer |
|---|---|---|
| B1 | **Fixed** (Phase 2, `20260816150000`). A view carries no row-level security of its own, and without `security_invoker` it ran as its **owner**, so the owner-scoped policies underneath were skipped; `GRANT … ON ALL TABLES` includes views, and the enablement loop reads `pg_tables`, which does not list them | Was: every account's two-factor method, lockout state and backup-code count readable — measured at **7 of 7** accounts from the application role. Now the caller's own row only |
| B2 | **Fixed** (Phase 2, `20260816160000`). Grants were table-wide; `pg_attribute.attacl` was NULL for **every column in the schema** | Was: no column protection anywhere. Now four columns carry their own grant |
| B3 | **Fixed** (Phase 2, `20260816160000`). `UPDATE` on `app_user` narrowed to `full_name` | Was: self-writes to `role`, `status`, `email_verified_at`, `password_hash` — all four measured as ALLOWED before |
| B4 | **Fixed** (Phase 2, `20260816160000`). `UPDATE` on `student_profile` narrowed to `language_pref` | Was: a Class 9 student could set `class_level` **and** `student_group` together and leave the consent gate. A check constraint made this look mitigated; it only rejects an inconsistent pair |
| B5 | **Fixed** (Phase 2, `20260816170000`). `FOR SELECT` + `FOR INSERT`, with `INSERT` narrowed to `(user_id, plan_code)` | Was: a user could set their own `status='active'`. `status` can no longer be supplied at all |
| B6 | **Fixed** (Phase 2, `20260816170000`). `FOR UPDATE … WITH CHECK (revoked = true)` — a one-way door | Was: revocation reversible. A column grant could not have fixed this; only a `WITH CHECK` forbids the inverse transition |
| B7 | **Fixed** (Phase 2, `20260816170000`). All five are `FOR SELECT` on the owner, with no write policy and no write grant | Was: every number a parent or teacher reads was student-writable |
| B13 | Six curriculum policies were changed to `USING (true)` | The bound-user requirement was dropped |
| B15 | `reqlog_insert` is `WITH CHECK (true)` | The operational log the admin panel reads is forgeable |
| B19 | **Closed structurally** (Phase 2). The fix is a test, not a migration: `test_rls_coverage.py` | Every future table is granted automatically and protected only if remembered — missed three times. The sweep now fails on any table without RLS forced and a policy, and any view not running as its caller |

B8–B12, B14, B16–B18 concern the classroom, quiz and OAuth tables and are catalogued on the database
page.

**What this means for reading the rest of this document.** Where a section below says a read or a
write "runs under Row-Level Security", that is a true statement about the mechanism — the binding
happens, the policy is evaluated. It is not a claim that the policy would refuse a request the
application should have refused. Until the B-series is fixed, treat every application-layer check in
`dependencies.py` and `service.py` as the **only** check.

Two things in the sweep *did* hold and are recorded so nobody re-audits them: **Card 1.5's
chat-privacy invariant** (`chat_session`, `message` and `visual_aid` are owner-only with no teacher,
parent or admin path, and no privileged function touches them), and **every `SECURITY DEFINER`
function carrying `SET search_path`** — the [database page](database.html) carries the measured count
and the per-function catalogue.

---

## 4. The `SECURITY DEFINER` escape hatch

### 4.1 Why pre-authentication paths need one

Login and refresh run **before there is a user to bind**. An owner-scoped policy such as
`app_user_self_read` (`USING (id = app.current_user_id())`) cannot be satisfied when
`app.current_user_id()` is unset — and unset means zero rows, not an error. So the login lookup would
return nothing for every account, and the code would read that as "no such user".

This is not hypothetical. `service.py:313-321` records the exact failure it caused before the fix:
reading `two_factor_enrollment` directly with no bound user matched `two_factor_enrollment_owner`
against an unset setting and returned zero rows for **every** account, which login read as "no
second factor yet". A user with active TOTP was handed an enrolment token, `/2fa/enroll` refused
because its own read happens after binding and saw the truth, and the account became unreachable
with the correct password and the correct authenticator.

### 4.2 The two options, and why the narrow one was taken

There are two ways out: connect as a role that bypasses Row-Level Security, or expose exactly the
columns the flow needs through a `SECURITY DEFINER` function. The project takes the second, and the
first is structurally discouraged — `get_service_db` exists (`core/db.py:86`) but its docstring says
"Background jobs only … Reaching for this from a route almost always means the real answer is a
narrow `SECURITY DEFINER` function instead", and `routes.py:81-85` records that **no route in the
file depends on it**.

### 4.3 The standing rule

From `backend/README.md:60-61`, verbatim:

> "If a new endpoint appears to need the service connection, add another narrow function rather than
> widening the door."

That is the rule. A function that returns four columns for one flow is auditable; a connection that
turns every policy off is not. The same instruction appears in the code at `core/db.py:20-24` and
again at `routes.py:83-85`.

### 4.4 The functions actually called from a request path

24 distinct `app.*` functions, 28 call sites:

> **Three counts appear across these pages and they do not conflict — each measures something
> different.** **24** distinct functions are *called from Python* (this page). **33** are *live in
> the database* ([`database.md`](database.md)) — 34 defined, one dropped as a duplicate. **37** is
> the number of `CREATE OR REPLACE FUNCTION` *statements*, which exceeds 33 because some functions
> are redefined by a later migration. The gap between 33 live and 24 called is real: nine functions
> exist and nothing in `app/` invokes them, one of which — `app.lookup_user_email` — has no call
> site anywhere at all.

```
grep -rnE "SELECT (\*|[a-z_, ]+) FROM app\.|SELECT app\." backend/app --include=*.py
```

| Function | Called from | Flow |
|---|---|---|
| `app.lookup_user_for_login` | `service.py:294` | login |
| `app.lookup_2fa_for_login` | `service.py:324` | login |
| `app.lookup_refresh_token` | `tokens.py:80` | refresh |
| `app.insert_auth_token` | `tokens.py:54` | every token issuance |
| `app.revoke_auth_token` | `tokens.py:119` | refresh rotation |
| `app.revoke_refresh_family` | `tokens.py:134` | reuse detection |
| `app.lookup_challenge_token` | `service.py:703`, `:785` | 2FA enrol / confirm |
| `app.start_2fa_challenge` | `service.py:907`, `:1028` | 2FA verify / resend |
| `app.upsert_2fa_enrollment` | `service.py:749`, `:762` | 2FA enrol |
| `app.issue_email_otp` | `service.py:569` | email OTP issuance |
| `app.lookup_email_otp` | `service.py:840`, `:958` | 2FA confirm / verify |
| `app.activate_2fa` | `service.py:856` | 2FA confirm |
| `app.verify_2fa_success` | `service.py:994` | 2FA verify |
| `app.verify_2fa_failure` | `service.py:671` | failed 2FA attempt |
| `app.replace_backup_codes` | `service.py:863` | 2FA confirm |
| `app.get_unused_backup_codes` | `service.py:975` | 2FA verify by backup code |
| `app.consume_backup_code` | `service.py:982` | 2FA verify by backup code |
| `app.consume_token_and_verify_email` | `service.py:1098` | email verification |
| `app.consume_password_reset_token` | `service.py:1193` | password reset |
| `app.check_token_status` | `service.py:601` | distinguishing `INVALID_TOKEN` from `TOKEN_EXPIRED` |
| `app.lookup_user_for_email_flow` | `service.py:624` | forgot-password / resend |
| `app.lookup_parent_id_by_email` | `service.py:1236` | guardian invite |
| `app.reinvite_guardian_link` | `service.py:1270` | guardian re-invite |
| `app.lookup_guardian_parent_email` | `service.py:1329` | guardian status |
| `app.confirm_guardian_link` | `service.py:1357` | guardian confirm |

> **Known defects C1 and C2.** Roughly ten of these functions accept a user identifier **without
> checking it belongs to the caller**. `app.insert_auth_token` (`tokens.py:54`) mints a token of any
> kind, for any user, with a caller-chosen hash — a complete authentication bypass if a
> request-controlled identifier ever reaches it. `app.confirm_guardian_link` does not check
> `p_parent = app.current_user_id()`. Both are **latent**: the review verified that **no current
> route passes a request-controlled identifier** to any of them. They are one route signature away
> from being live, which is why the standing rule in §4.3 is a rule and not a preference. Signatures
> and grants are catalogued on the [database page](database.html).

---

## 5. The lifecycle of an authenticated request

`architecture.html` carries this as a rendered Mermaid sequence diagram. The same content in text:

```
Client                Route              authenticated dep       PostgreSQL (app_backend)
  │  Authorization: Bearer <JWT>
  ├───────────────────►│
  │                    │  enforce(...)  ← in-process, no I/O   core/ratelimit.py:117
  │                    ├──────────────────►│
  │                    │                   │  decode_access_token   auth/security.py:92
  │                    │                   │  (signature + type=="access"; no database)
  │                    │                   │
  │                    │                   │  ROUND TRIP 1 ─────────►│  SELECT set_config(
  │                    │                   │                         │    'app.current_user_id',
  │                    │                   │                         │    :uid, true)
  │                    │                   │                         │  core/db.py:56
  │                    │                   │  ROUND TRIP 2 ─────────►│  SELECT status, role
  │                    │                   │                         │  FROM app_user
  │                    │                   │                         │  WHERE id = :uid
  │                    │                   │                         │  ← evaluated under
  │                    │                   │                         │    app_user_self_read
  │                    │                   │  dependencies.py:68
  │                    │  AuthContext(session, user_id, role)
  │                    │◄──────────────────┤  dependencies.py:82
  │                    │
  │                    │  service function ─── business queries ────►│  same transaction,
  │                    │                                             │  same binding
  │  200 + X-Request-ID│
  │◄───────────────────┤
                                             session.commit()  dependencies.py:83
```

**Two round trips happen before any business logic**, and they are not interchangeable. The first
writes the binding; the second proves the token's subject is a real, active, non-deleted user — and
because it runs *after* the binding, that proof is itself evaluated by Row-Level Security rather than
around it. Reversing them would leave the identity check running with no user bound, which returns
zero rows and reads as "no such user" for everyone.

`set_current_user_id` binds at **round trip 1** and the binding lives until `session.commit()` at
`dependencies.py:83` or `session.rollback()` at `dependencies.py:85`. Everything in between —
including every query the service layer makes — shares that one transaction and that one binding.

---

## 6. The seven token kinds

`TokenKind` (`app/models/enums.py:54`) mirrors the PostgreSQL `token_kind` enumeration. Every one is
stored in `auth_token` as a **keyed hash**, never in plaintext: `hash_token`
(`auth/security.py:48`) is HMAC-SHA256 (Hash-based Message Authentication Code) over the token with
`jwt_refresh_secret` as the key, prefixed `hmac-sha256:`. The docstring at `service.py:560-562`
records why a keyed hash and not a bare digest: a six-digit OTP is a million possibilities, and a
plain SHA of that space is a rainbow table, whereas an HMAC is useless to anyone holding a database
dump but not the application secret.

| Kind | Lifetime | Where it lives | The endpoint(s) that accept it |
|---|---|---|---|
| `refresh` | `refresh_token_ttl_days`, default **7 days** (`core/config.py:50`) | `auth_token`, hashed. Plaintext goes **only** into an httpOnly, path-scoped `refresh_token` cookie (`routes.py:119-132`) — deliberately absent from `AccessTokenResponse` (`routes.py:133-139`) | `POST /api/auth/refresh` only |
| `two_factor_enrollment` | `enrollment_token_ttl_seconds` = **900 s** (`core/config.py:51`) | `auth_token`, hashed. Plaintext returned in the login response body | `POST /api/auth/2fa/enroll`, `POST /api/auth/2fa/confirm` |
| `two_factor_pending` | `pending_token_ttl_seconds` = **300 s** (`core/config.py:52`) | `auth_token`, hashed. Plaintext returned in the login response body | `POST /api/auth/2fa/verify`, `POST /api/auth/2fa/resend` |
| `two_factor_email_otp` | **600 s** (`_EMAIL_OTP_TTL_SECONDS`, `service.py:95`) | `auth_token`, hashed. The six-digit code is emailed | `POST /api/auth/2fa/confirm`, `POST /api/auth/2fa/verify` — as the `code` field, not as the credential |
| `email_verify` | **3600 s** (`_EMAIL_LINK_TTL_SECONDS`, `service.py:92`) | `auth_token`, hashed. Plaintext in an emailed link | `POST /api/auth/email/verify` |
| `password_reset` | **3600 s** (same constant) | `auth_token`, hashed. Plaintext in an emailed link | `POST /api/auth/password/reset` |
| `guardian_invite` | **7 days** (`ttl_seconds=7 * 86400`, `auth/tokens.py:226`) | `auth_token`, hashed, with the **student** as `user_id` — the gate subject, not the redeemer | `POST /api/auth/guardian/confirm` |

Alongside these sit two JWTs, which are **not** rows in `auth_token` and are not revocable:

| JWT `type` claim | Lifetime | Issued by | Accepted by |
|---|---|---|---|
| `access` | `access_token_ttl_minutes`, default **15 min** (`core/config.py:49`) | `create_access_token` (`auth/security.py:58`) | every authenticated route, via `decode_access_token`'s default `expected_type="access"` (`auth/security.py:92`) |
| `onboarding` | same 15 min | `create_onboarding_token` (`auth/security.py:78`); issued by `verify_email` (`service.py:1111-1114`) | **nothing yet.** The default decode requires `type == "access"`, so this token is rejected by every business route including `/auth/me` — which is exactly the `tdd.md` §3.1 rule that email verification alone must not become a complete login |

> **Known defect E2.** An issued access token cannot be revoked. Logout revokes refresh tokens only
> (`service.py:407`), so a stolen access token remains valid for the rest of its 15 minutes.

### 6.1 Why `two_factor_pending` and `two_factor_enrollment` are separate kinds

They were originally the same kind. Migration
`supabase/migrations/20260802140100_token_kind_enrollment.sql` added the second value, and its
header states the reason directly:

> "Login issues two different short-lived credentials: an ENROLMENT token (~900 s) for a user who
> has no second factor yet, which `/2fa/enroll` and `/2fa/confirm` accept; a PENDING token (~300 s)
> for a user who has one, which `/2fa/verify` exchanges for a FULL SESSION. Both were being stored
> as kind `'two_factor_pending'`, so nothing could tell them apart. That means `/2fa/verify` cannot
> reject an enrolment token — a longer-lived credential, issued for a weaker purpose, presented at
> the one endpoint that hands out a session."
> — `20260802140100_token_kind_enrollment.sql:6-16`

**The kind is the only thing that can enforce that boundary**, so it has to differ. Three
consequences visible in the code:

1. `issue_challenge_token` (`auth/tokens.py:165`) makes `kind` a **required** keyword argument and
   raises `ValueError` for anything that is not one of the two 2FA kinds (`tokens.py:183-184`). The
   caller must say which it means.
2. `login` picks between them on the enrolment's status: enrolment token when there is no active
   second factor (`service.py:348-353`), pending token when there is (`service.py:360-365`).
3. `/2fa/verify` filters on `TokenKind.two_factor_pending.value` inside
   `app.start_2fa_challenge` (`service.py:907-911`) — in SQL, together with `revoked = false` and
   `expires_at > now()`, which is what makes an enrolment token presented there return zero rows
   rather than a session.

The migration also records why it is a file of its own: PostgreSQL will not let a value added by
`ALTER TYPE … ADD VALUE` be *used* in the same transaction, and the Supabase CLI runs each migration
in one.

A parallel guard exists for the other pair: `issue_preauth_token` (`auth/tokens.py:192`) accepts
only `email_verify` and `password_reset` and raises otherwise (`tokens.py:213-214`), so a
`password_reset` token can never be minted through the 2FA path.

---

## 7. The onboarding state machine

`derive_onboarding_state` (`app/auth/onboarding.py:17`) is the whole machine — five states, one
precedence order, evaluated top to bottom, first match wins. `architecture.html` carries it as a
Mermaid flowchart.

The module is **deliberately free of database and settings imports** (`onboarding.py:4-11`). This is
the single field the frontend routes on and every rule in it is a product decision, so it has to be
assertable in `tests/unit` without a connection string. It mirrors `frontend/lib/auth/onboarding.ts`
on the other side of the contract.

| Order | Condition | State |
|---|---|---|
| 1 | `not email_verified` | `email_verification_pending` (`onboarding.py:40-41`) |
| 2 | `not two_factor_active` | `two_factor_enrollment_pending` (`onboarding.py:42-43`) |
| 3 | `guardian_required and guardian_status != "verified"` | `guardian_link_pending` (`onboarding.py:44-45`) |
| 4 | student **and** `subscription_status` is `None` or not in `{"trialing", "active"}` | `plan_selection_pending` (`onboarding.py:46-49`) |
| 5 | otherwise | `active` (`onboarding.py:50`) |

`ACTIVE_SUBSCRIPTION_STATUSES` is `frozenset({"trialing", "active"})` (`onboarding.py:14`).

### 7.1 It is not monotonic

**Rule 4 can fire after a user has already been `active`.** A student's 14-day trial lapses and they
move *backwards* from `active` to `plan_selection_pending`. This is the only backward transition in
the system, and the docstring names the consequence (`onboarding.py:34-37`): a consumer that
evaluates the state once at session start and caches `active` will strand that user on a page they
no longer have rights to. The state must be re-evaluated on every identity check — which is why
`me()` (`service.py:487`) is on the hot path and does not cache.

The response schema encodes this too. `MeResponse.onboarding_state` is a five-member `Literal`
(`auth/schemas.py:228-234`) and the comment above it (`schemas.py:223-227`) records why omitting
`plan_selection_pending` would not merely hide a screen: paid access would never be enforced,
because a lapsed student would keep reporting `active` forever.

### 7.2 Rule 4 fails closed

No subscription row means **no access**, never "still trialing" (`onboarding.py:38-39`, `prd.md`
MON-2). A failed insert at registration must not silently grant indefinite free use. Registration
therefore inserts the `subscription` row in the same transaction as the profile
(`service.py:166-169`), leaving `status` and `trial_ends_at` to their schema defaults so that
`trial_ends_at DEFAULT (now() + interval '14 days')` stays the single definition of trial length.

### 7.3 One derivation, not four

`onboarding_state_for` (`service.py:441`) is the single call site of the derivation for every
endpoint that reports the field. Its docstring (`service.py:447-453`) records that there were
previously four copies — `/2fa/confirm`, `/2fa/verify` and `/email/verify` each rebuilt the
derivation inline with its own `class_level in (9, 10)` test and its own guardian lookup — and that
the copies did **not** apply the fail-closed rule in `gate.py`, so a student with a missing or
unreadable `student_profile` row would be told `active` by `/email/verify` and `guardian_link_pending`
by `/auth/me` in the same session.

The `two_factor_active` override parameter exists because the 2FA endpoints call this in the same
transaction that activates the enrolment; re-reading a row just written in order to learn what was
written is what silently breaks when the binding or the isolation level changes.

> **Known defect D13.** `onboarding_state` is a `Literal` on `MeResponse` (`schemas.py:228`) and a
> plain `str` on four other response models, so only one of the five responses that carry it is
> validated against the state set.

---

## 8. The guardian gate

`prd.md` §4.3 (line 275) requires that a Class 9–10 student cannot use the learning endpoints until
a parent confirms an out-of-band invitation. `user-stories.md:154-175` is Card 1.6.

### 8.1 The decision is a pure function

`app/auth/gate.py` holds two functions and no imports at all:

- `guardian_required(*, is_student, class_level)` — `gate.py:18`. Returns `True` for a student whose
  `class_level` is 9, 10, **or `None`**. Teachers, parents, administrators and Class 11–12 students
  are never required to link a guardian.
- `is_guardian_gate_pending(*, is_student, class_level, guardian_status)` — `gate.py:38`. Returns
  `False` when the gate does not apply; otherwise returns `guardian_status != "verified"`.

Like `onboarding.py`, this module is deliberately free of database and settings imports
(`gate.py:4-8`) so the decision is assertable in `tests/unit` without a connection string — and so
that `me()` (`service.py:504`), `guardian_status()` (`service.py:1321`) and
`require_guardian_verified` (`dependencies.py:196`) cannot drift apart on the Class 11–12 rule. All
three call the same two functions.

### 8.2 Why Row-Level Security cannot express it

The module docstring states it (`gate.py:10-14`):

> "The gate is an APPLICATION-layer decision on purpose: 'class 9-10 student whose guardian is not
> verified' is not expressible as a Row Level Security policy (RLS cannot branch on the status of a
> row in another table per-access)."

A policy is a predicate over the row being accessed. The gate is a predicate over *two other* rows —
the student's `student_profile.class_level` and the status of a representative `guardian_link` — and
it must hold for tables (`chat_session`, `attempt`, and the rest) that have no relationship to
either. The database's contribution is narrower and different in kind: the learning tables are
student-owner-only anyway, so the gate is about *whether the student may act at all*, not about
*whose rows they may touch*.

This is the clearest example of why the two layers are not redundant copies of each other. Some
rules only the application can express; some only the database can enforce. Which is why §3.3
matters — losing one of them is not losing a duplicate.

### 8.3 Fail-closed on an unreadable class level

**A student whose `class_level` is unknown is gated.** `guardian_required` returns `True` for
`class_level is None` (`gate.py:35`), and the docstring records the reasoning (`gate.py:27-31`):
`None` means the `student_profile` row was missing or unreadable, and under Row-Level Security an
unreadable row is **indistinguishable from an absent one** — which is also exactly what a forgotten
binding looks like. The failure mode of guessing wrong is serving a 14-year-old as though they were
18.

The two functions agree on this deliberately. If `is_guardian_gate_pending` held the gate while
`guardian_required` reported "not required", `onboarding_state` would say `active` while every
learning endpoint returned 403 — a student blocked from everything with no screen on which to fix
it.

`require_guardian_verified` (`dependencies.py:158`) supplies the inputs, both read under Row-Level
Security as the student: `class_level` from `student_profile` (`dependencies.py:174-177`) and the
representative guardian status from `guardian_link`, ordered `(status = 'verified') DESC,
created_at DESC LIMIT 1` (`dependencies.py:183-189`) so that a student with several parent links
gets the most favourable one. A pending gate raises `GATE_PENDING` (403, `core/errors.py:73`).

> **Note.** `require_guardian_verified` is exported and tested but **wired to no route** — the
> learning endpoints it protects (`/api/tutor/*`, `/api/practice/adaptive`, `/api/quiz/*/attempts*`,
> `/api/reports/*`) are among the 31 that do not exist. See [api-endpoints.md](api-endpoints.md).

### 8.4 The write boundary

Neither participant can write `verified`. The student's `INSERT` into `guardian_link` runs under
`guardian_link_create` as the student (`service.py:1261-1268`), but the **reset to pending** goes
through `app.reinvite_guardian_link` (`service.py:1270`), a privileged function that can only ever
write `pending` (migration `20260803090000`). The comment at `service.py:1252-1260` records why
widening `guardian_link_update` is not the fix: a student who can update their own link can set
`verified` and clear their own gate.

Confirmation is parent-only at the route (`routes.py:335`, `require_role(UserRole.parent.value)`),
and the atomic flip lives inside `app.confirm_guardian_link` (`service.py:1357`), which returns the
status *before* the transition so the three outcomes can be told apart.

> **Known defects A10 and C3.** The guardian invitation email is **never sent** — `guardian_invite`
> (`service.py:1210`) issues the token but makes no `_queue_email` call, and
> `guardian_invite_email` (`auth/email_templates.py:118`) has no caller. This was **deferred by the
> user**. C3 is latent only because of that: `student_name` is interpolated unescaped into that
> template, which would be HTML injection into a parent's inbox from a verified sending domain.
>
> **Known defect D3.** Card 1.6's own failure criterion (`user-stories.md:172`) — "a student
> satisfies their own gate by registering a throwaway parent account" — is satisfiable today.

---

## 9. Cross-cutting mechanisms

### 9.1 The email seam — `app/auth/email.py`

A `Protocol` with one method (`email.py:33-36`) and two implementations:

| Sender | File:line | Behaviour |
|---|---|---|
| `LoggingEmailSender` | `email.py:54` | Writes the message **including the one-time code or link** to the logger |
| `ResendEmailSender` | `email.py:79` | Sends via the Resend REST API; the SDK is an optional extra (`uv sync --extra email`) |

`get_email_sender` (`email.py:113`) picks on `settings.email_provider`. Logging the body is
deliberate (`email.py:58-67`): the OTP is stored as an HMAC hash, so a code that is neither
delivered nor logged cannot be recovered by anyone, and 2FA enrolment by email simply could not be
completed on a developer machine. The safety of that decision rests entirely on
`_production_is_actually_hardened` (`core/config.py:166-171`) refusing to start with
`EMAIL_PROVIDER=logging` in production.

**Dispatch is asynchronous, and that is a security control, not a performance one.**
`send_async` (`email.py:167`) submits to a two-worker `ThreadPoolExecutor`. The comment at
`email.py:127-137` explains: `password/forgot` and `email/resend` must answer identically for a
known and an unknown address in **body, status and timing**, and the dummy argon2 verify was
equalising the wrong thing — the known-address branch went on to make a synchronous HTTP request to
the mail provider, hundreds of milliseconds the unknown-address branch never paid. Anyone with a
stopwatch could enumerate the user table. `drain_pending_emails` (`email.py:173`) exists for tests
and graceful shutdown.

> **Known defects A3, D1 and D8.** `email_provider` is an unvalidated string, so a typo falls
> through to the logging sender *and* past the production guard at `config.py:166`, writing every
> two-factor code and reset link to stdout. Emails are dispatched **before** the transaction commits
> (`service.py:198` runs before `get_db`'s commit), so a rolled-back registration still sends a
> verification link. The queue leaks a `Future` per message into `_pending` (`email.py:170`) and its
> drain is not atomic.

### 9.2 The error envelope — `app/core/errors.py`

Every error the API returns has one shape (`errors.py:109`):

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

`AppError` (`errors.py:11`) carries `code`, `message`, `status_code` and `details`. Sixteen
factory functions build the catalogued errors — `validation_error` (`:27`), `unauthenticated`
(`:31`), `two_factor_locked` (`:35`), `email_already_registered` (`:44`), `invalid_class_group`
(`:52`), `rate_limited` (`:56`), `captcha_failed` (`:60`), `forbidden_scope` (`:69`), `gate_pending`
(`:73`), `self_link_forbidden` (`:77`), `guardian_already_linked` (`:81`), `invalid_token` (`:85`),
`guardian_not_found` (`:89`), `two_factor_invalid` (`:93`), `pending_token_expired` (`:97`),
`token_expired` (`:105`).

**No endpoint invents a code.** `tdd.md` §7.3 (line 1073) states the rule, and the code follows it at
`service.py:1057-1065`: `/2fa/resend` against a TOTP enrolment answers `400 VALIDATION_ERROR` with
`details.fields`, not a bespoke `INVALID_METHOD`, because a code outside the catalogue reaches the
client as an unrecognised string and renders as "something went wrong".

Three handlers are registered (`errors.py:170-173`): `AppError`, FastAPI's `RequestValidationError`
(flattened into `details.fields`, `errors.py:122`), and a catch-all. The catch-all
(`errors.py:138`) **logs the exception** — which it previously did not — and returns a body that
says nothing beyond the request id, because a stack or a database message can carry an email
address, a token fragment or an internal path (`errors.py:145-150`).

`INVALID_TOKEN` versus `TOKEN_EXPIRED` is not a coin toss. `_raise_for_token_status`
(`service.py:583`) calls `app.check_token_status` and returns `410 TOKEN_EXPIRED` **only** for a
token that lapsed unused; a token that was already spent is `400 INVALID_TOKEN`, because offering a
resend for a link that already worked sends the user round a loop they have finished
(`service.py:588-595`).

### 9.3 Configuration validation — `app/core/config.py`

`Settings` (`config.py:10`) reads `backend/.env` through pydantic-settings. The class docstring
(`config.py:11-24`) records a real, silent failure: pydantic-settings matches on the **field name**,
so `environment` looked for `ENVIRONMENT` while `.env.example` set `APP_ENV`, which was therefore
ignored — along with `JWT_ACCESS_TTL_MINUTES` and `JWT_REFRESH_TTL_DAYS`. Because `environment`
gates `/docs` exposure and the refresh cookie's `secure` flag, a deployment stayed in development
mode no matter what the file said, and `extra="ignore"` meant nothing ever complained. **Every field
whose environment key differs from its name now carries an explicit `validation_alias`.**

Four validators refuse to start rather than run misconfigured:

| Validator | File:line | Refuses |
|---|---|---|
| `_secret_is_strong_enough` | `config.py:106` | `jwt_secret` / `jwt_refresh_secret` under 32 characters or starting `CHANGE_ME` |
| `_totp_key_must_be_a_fernet_key` | `config.py:120` | a `TOTP_ENCRYPTION_KEY` that is a placeholder or not a valid Fernet key — Fernet raises at *first use*, which would otherwise be the middle of a user's 2FA enrolment, as a 500 |
| `_turnstile_key_is_not_a_placeholder` | `config.py:145` | the placeholder `TURNSTILE_SECRET_KEY` |
| `_production_is_actually_hardened` | `config.py:159` | `"*"` in `cors_origins` in production; `EMAIL_PROVIDER=logging` in production; `resend` without `EMAIL_FROM` |

`totp_encryption_key` and `turnstile_secret_key` have **no defaults** on purpose
(`config.py:58-63`): a defaulted encryption key is worse than a missing one, because every
deployment that forgot to set it would share the same key and nobody would find out.

> **A3, A4, A5 and D11 — FIXED, Phase 1 (2026-08-16).**
>
> All four had the same shape: a setting typed as a bare `str`, and consumers comparing it for
> equality against one expected spelling. Anything else raised nothing — it matched no branch and
> fell through to the default, and **every one of those defaults was the insecure one.**
>
> - `environment` and `email_provider` are now `Literal` types, so a value outside the closed set is
>   a **boot failure** rather than a silent downgrade. `APP_ENV=prod` used to read as *development*
>   in production: `/docs` served, the logging sender permitted, and `secure` dropped from the
>   refresh cookie. `EMAIL_PROVIDER=Resend` matched neither `"resend"` nor `"logging"`, so it
>   selected the logging sender **and** passed the production guard, which also tested
>   `== "logging"` — every two-factor code and reset link to stdout.
> - `_normalise_choice` (`mode="before"`) trims and lower-cases first, so `Production ` starts and
>   `prod` still fails. Formatting is forgiven; guesses are not.
> - `openapi_url=None` in production. `docs_url` gates only the Swagger HTML; the schema route kept
>   its default and published the whole surface unauthenticated.
> - `app_base_url` must begin `https://` in production. Left at its localhost default it mails links
>   nobody can open; over `http://` it puts single-use reset tokens in cleartext.
>
> A guard that already existed became **reachable** as a side effect: `EMAIL_PROVIDER=Logging`
> previously bypassed the production check *and* selected the thing that check exists to prevent.
> Pinned by `tests/unit/test_config_hardening.py`.

### 9.4 Captcha, passwords and TOTP

`verify_turnstile_token` (`auth/turnstile.py:23`) **fails closed**: a network failure, a non-JSON
body or a non-boolean `success` all return `False` (`turnstile.py:45-53`). The raw Cloudflare
`error-codes` are logged and never returned — the client gets one generic `CAPTCHA_FAILED`
(`turnstile.py:4-7`). It is called first in both `register` (`service.py:102`) and `login`
(`service.py:286`), **before** the lookup and before the dummy-hash branch, so the captcha is a
constant cost for every account and never reveals whether an address exists.

Passwords are **argon2id** (`auth/security.py:26-30`), with the hasher built on first use rather
than at import so the unit tests do not need database credentials they never touch
(`security.py:17-24`). Login runs a **dummy verify** on the unknown-account branch
(`service.py:304`) against a real argon2 hash computed once (`service.py:258`), because
short-circuiting would answer in about a millisecond while a wrong password paid the full cost —
a gap measurable from anywhere, which `tdd.md` §6.11 forbids "by body, status code, OR TIMING".

TOTP secrets are encrypted with Fernet before storage (`auth/totp.py:104`), with the key in
application configuration and not in the database, so a database dump alone yields no usable secrets
(`config.py:54-56`). Backup codes are argon2id-hashed (`auth/backup_codes.py:33`), which is why
verification iterates the unused hashes (`service.py:974-986`) instead of doing a hash lookup.

> **Known defects A9, D7 and A7.** `/2fa/enroll` skips the lockout check (`service.py:688` has no
> `locked_until` branch, unlike `two_factor_confirm` at `service.py:824-826`) — **and it sends
> mail**. The TOTP check passes a float where a `datetime` is expected. Backup-code download can
> silently produce no file, and the codes are shown once and then lost.

---

## 10. Cross-references

| Document | What it is | Where |
|---|---|---|
| `prd.md` | Product Requirements Document — the four roles, the monetisation model, §4.3 the parental-consent gate (line 275), MON-2 the fail-closed subscription rule | [`../../prd.md`](../../prd.md) |
| `tdd.md` | Technical Design Document — §3.1 the auth component and its endpoint table (line 165), §6.8 Row-Level Security (line 858), §6.9 two-factor authentication (line 893), §6.11 client-side security (line 988), §7.2 the consolidated endpoint catalogue (line 1026), §7.3 the error model (line 1043) | [`../../tdd.md`](../../tdd.md) |
| `user-stories.md` | 12 epics. Card 1.5 Access Control and Row-Level Security (line 129), Card 1.6 Guardian Invitation and Confirmation (line 154) | [`../../user-stories.md`](../../user-stories.md) |
| `database.html` / `database.md` | Tables by domain, the **complete Row-Level Security policy catalogue**, the `app.*` privileged functions with signature and grant, and findings B1–B19 | [database.html](database.html) |
| `api-endpoints.md` | Every implemented route → handler → service function with `file:line`, mapped to its `tdd.md` §3.1 row, plus the explicit list of the 31 specified-but-missing routes | [api-endpoints.md](api-endpoints.md) |
| `backend/README.md` | Environment variables, the running and testing commands, and the standing `SECURITY DEFINER` rule quoted in §4.3 | [`../README.md`](../README.md) |

### Rendering the diagrams offline

`architecture.html` loads Mermaid from `assets/mermaid.min.js` — a **local vendored copy, never a
Content Delivery Network**. This project is demonstrated in a viva room, and a diagram that fails to
render because the network is unreliable is worse than a static image. The bundle is committed at
`backend/Architecture/assets/mermaid.min.js`, so both HTML pages render with the network disabled.
If that file is ever removed, the diagram source shows as plain text inside its panel — legible, but
unstyled.

---

*Snapshot 2026-08-15. This document records the system as it stands, including known defects. It is
not a description of the intended end state — for that, read `tdd.md`, and read
[api-endpoints.md](api-endpoints.md) for the gap between the two.*
