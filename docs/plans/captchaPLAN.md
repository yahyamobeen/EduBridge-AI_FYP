# Implementation Plan — Cloudflare Turnstile CAPTCHA on Registration & Login

**Task:** Add Cloudflare Turnstile verification to `POST /api/auth/register` and `POST /api/auth/login` only.

**Scope guard (rule 7):** password reset, email verify/resend, 2FA enroll/verify/resend, and the guardian invite/confirm flows do **not** get a Turnstile checkbox in this task, even though they share the error-envelope and rate-limit plumbing. Nothing in this plan touches them.

---

## ⚠ OPENING SUMMARY: THIS IS A BREAKING CHANGE TO SHARED CONTRACT TYPES

`RegisterRequest` and `LoginRequest` (backend `app/auth/schemas.py` L35–47, L120–122; frontend `lib/api/types.ts` L61–72, L82) are shared contract types. Every teammate's in-progress branch builds against them — the backend README explicitly splits ownership of 2FA (Muneeb) and the guardian flow (Mujtaba), both of which construct or consume these schemas. Adding a **required** `turnstile_token: str` field to both is **breaking**: any caller, test, mock, or future branch that posts a register/login body without the field now gets `400 VALIDATION_ERROR` with a per-field `turnstile_token` message (FastAPI/Pydantic's automatic shape validation — same envelope the student-fields check already uses).

**Before merging, this must be coordinated with the team — it is not "just adding a field."** Recommended: raise it in the team's channel when Phase 5 lands, with the wording that password/reset/2FA endpoints are unaffected. See Open Question 4.

Branches observed at plan time:
- Current branch: `feature/cloudfare-captcha`.
- `feature/confirm-password` exists and is **NOT merged into main** (verified: `git merge-base --is-ancestor` fails). The confirm-password plan (`plan.md`) is a separate exercise.
- The current `main` (`0a74318`, "Merge pull request #10 …") does **not** carry `confirmPassword` fields in either signup form (read from the checked-out tree).

**Assumed case (stated for the record):** at the time this plan is *executed* the contract change is assumed to still be on top of main *without* the confirm-password branch merged; BUT the plan is written so it is safe either way — Turnstile is ADDED to the three forms as a separate element with its own i18n namespace (`auth.*`, `signup.errors.captchaFailed`), never interleaved with a `confirm_password` field if one arrives later, and no shared helper or form field is modified in a way that would conflict.

---

## Grounding (files read before writing this plan — every decision ties back to one of these)

| File | What it establishes |
|---|---|
| `backend/app/core/config.py` | `Settings` pattern: `validation_alias`, required-with-no-default + validator that **refuses to start on a placeholder** (`_totp_key_must_be_a_fernet_key` L114–137). Model validator `_production_is_actually_hardened` (L139–154) for production-only refusals. |
| `backend/app/auth/schemas.py` | `RegisterRequest` L35–47 (student-field validation methods called *from the service, not the route*), `LoginRequest` L120–122. |
| `backend/app/auth/service.py` | `register()` L96–197 (validates first, then binds `set_current_user_id`, then inserts); `login()` L264–356 — **the constant-time dummy hash** `_dummy_password_hash()` L249–261, both branches performing exactly one argon2 verify (L287–292). |
| `backend/app/auth/routes.py` | `enforce(request, bucket=…)` runs **before** the service call (L96, L105) — so *any* request, including one that will later be captcha-rejected, already consumes its bucket. |
| `backend/app/core/errors.py` | `AppError` factory pattern (L11–24), `error_envelope` (L100), `_unhandled_error_response` (L129–158) — the precedent for **never leaking internals** in a client-facing body. |
| `backend/app/core/ratelimit.py` | `LOGIN_LIMIT=10/60s`, `REGISTER_LIMIT=5/300s` (L39–40); `enforce()`/`enforce_subject` split; the in-process fixed-window disclaimer (L13). |
| `backend/pyproject.toml` | `httpx>=0.27.0` present **only under `dev`** (L31). The runtime needs it for siteverify → it must be **moved** to `[project].dependencies`, not added. `[tool.ruff]` line length 100. |
| `backend/tests/integration/conftest.py` | `never_send_real_email` (L77–102): autouse, `monkeypatch.setattr(module, "get_email_sender", LoggingEmailSender)`, patches the seam at import time (because `get_settings` is lru_cached) — the template for `never_call_turnstile`. Also: rollback-savepoint fixtures, `reset_for_tests`. |
| `backend/tests/unit/test_security.py` | (exists — config validation tests land here). |
| `backend/tests/integration/test_login_discriminator.py` | L90/104/115/132/144/159 construct `LoginRequest(email=…, password=…)` **directly** — pydantic will scream without the new field. This is exactly the "update the fixture, don't weaken the assertion" case (rule 5). |
| `backend/tests/integration/{test_register.py,test_auth_flows.py,test_refresh_flow.py,test_email_password.py}` | POST raw JSON to `/api/auth/register` and `/api/auth/login` — their inline JSON bodies must each gain `"turnstile_token": TEST_TOKEN`. |
| `frontend/components/auth/LoginForm.tsx` | `canSubmit` gates on fields + `!rateLimited`; `noRetry` is passed from `endpoints.ts`; error branch on `error.code`; `FormBanner` for form-level errors. |
| `frontend/components/signup/StudentSignupForm.tsx` | 3-step, `basicComplete`/`academicComplete`, submit disabled gates. |
| `frontend/components/signup/SimpleSignupForm.tsx` | single-step, `complete` gate. |
| `frontend/lib/api/types.ts` | Frontend mirror of backend schemas. |
| `frontend/lib/api/endpoints.ts` | `login()` → `apiFetch(…, { noRetry: true })` (L160–162). |
| `frontend/lib/api/errors.ts` | `ERROR_CODES` (L9–33) — the allow-list of codes the UI is allowed to branch on; `isRefreshableAuthError` (L94–97) is an allow-list (UNAUTHENTICATED, UNKNOWN). |
| `frontend/lib/api/client.ts` | `apiFetch` retry discipline: `init.bearer === undefined && !init.noRetry && isRefreshableAuthError`. A captcha failure therefore **cannot** trigger a refresh — see §5.6. |
| `frontend/next.config.mjs` | CSP has `script-src 'self' 'unsafe-inline'`, **no `frame-src`**, `connect-src 'self'` + apiOrigin. Cloudflare widget needs both `script-src https://challenges.cloudflare.com` AND `frame-src https://challenges.cloudflare.com`. |
| `frontend/.env.example` | `NEXT_PUBLIC_` prefix convention, comment style. |
| `frontend/package.json` | The `overrides` comment is a stated precedent: this repo **deliberately adds third-party packages under duress** and curates their advisories — feed the widget-vs-package decision (see 5.3). |
| `frontend/lib/api/mock/{index,db}.ts` | Mock register/login handlers — must accept a `turnstile_token` so mock mode stays working (dev-only; rules of contract mirroring). |
| `frontend/messages/en.json` | namespaces `signup.common`, `signup.errors`, `auth.errors` — where the new keys live. |

---

## Cloudflare siteverify — shape note (do not speculate from memory)

`verify_turnstile_token()` reads exactly two fields from the POST response:
- `success` (boolean) — pass/fail;
- `error-codes` (array of strings) — logged server-side **only**, never returned to the client.

The **exact** response schema, the siteverify URL, and the published **test site/secret key values** must be re-verified against Cloudflare's current docs at implementation time (third-party shapes and test keys drift). The plan pins the design (what is read, where it goes), not the third-party surface — which is applyable with no code change if the shapes are unchanged.

---

## Stress-test passes (done on this plan before writing it final)

### PASS 1 — "try to break it" findings, then fixes

| Threat / bug | Found? | Fix in this plan |
|---|---|---|
| Live network call to Cloudflare during `pytest` | ❗ **Real risk.** `httpx` is in dev deps; nothing stops the service from calling siteverify under test. | Autouse `never_call_turnstile` fixture in `tests/integration/conftest.py`, monkeypatching the verify seam (same shape as `never_send_real_email`). Unit tests monkeypatch `httpx` too — never a real network call. **No Cloudflare test keys are used** — the fixed test keys still entail a live HTTP call, which the requirement forbids. |
| CAPTCHA runs AFTER the password branch in `login()` (timing leak) | **The single highest-risk ordering.** | Verdict is the **first executable statement** of `login()` — before the `SECURITY DEFINER` lookup, before the dummy-hash branch. Same for `register()`. Call plus a unit test asserting ORDER via a spy. |
| Stale/reused Turnstile token accepted on retry | Real risk if the form holds the token across submit | Every failed submit (any error) resets the widget (token is single-use; siteverify in `login()` runs before the password check, so a bad password has already consumed it). Submit stays disabled until a fresh `onVerify` fires. |
| Widget never reset after failure → silent block | Same as above, client side | Imperative `reset()` on the widget (bump a `nonce` prop → effect calls `window.turnstile.reset(widgetId)`), plus test that old token is cleared. |
| The secret key in a frontend env var (`NEXT_PUBLIC_`) | ❗ **Absent risk.** Human puts `TURNSTILE_SECRET_KEY` only in `backend/.env`. Frontend gets only the *site* key | Env split enforced structurally: `TURNSTILE_SECRET_KEY` has no `NEXT_PUBLIC_` prefix anywhere in this repo; plan states the rule. |
| `turnstile_token` missing in one of the three forms | Real risk (copy-paste of a gating block onto only two forms) | Each form's gate is spelled in its BEFORE/AFTER below — all three, same pattern: a state field + a `Turnstile` render + gate invalidation + reset onClick. A test asserts all three forms submit only with a token. |
| Cloudflare `error-codes` leaking into the client-facing message | ❗ | `captcha_failed()` returns only the generic message; the raw codes go to the `edubridge` logger under `logger.warning`, never into `AppError.details`. Follows `_unhandled_error_response` L129–158 precedent. |
| Breaking shared contract silently | ❗ | Summary at top of this plan + Open Question 4 (explicit team sign-off) + PR coordination bullet. |
| `httpx` removed from dev/$\u2014$\u2014 violation of "no new dependency" | Found on review of pyproject | Move the existing `httpx>=0.27.0` line from `dev` to `[project].dependencies` — **not** a new package. Regenerate lockfile and both exports per `backend/README.md` L80–82. |
| CSP blocks the widget silently (iframe + script) | ❗ `script-src` lacks challenges.cloudflare.com and there is no `frame-src` at all | next.config.mjs: add `https://challenges.cloudflare.com` to both directives; preserve the existing comment discipline explaining why (mirror L7–23 style). |
| Mock prod builds : site key in production bundle is fine (it is public); the **secret** must not be | Note | Site key is public by design (same as `NEXT_PUBLIC_API_BASE_URL`); secret never has the prefix — no production risk. |

### Pass 2 — re-review after Pass-1 fixes

Re-checked the five non-regression items (see §8) against the final plan and verified:
- confirm-password: untouched in the plan's phases; if it merges first, only the same forms get a *separate* widget element.
- constant-time login: untouched — the only change to `login()` is the captcha line, physically above the lookup.
- refresh/session logic: no line in `client.ts`/`errors.ts` touching `REFRESHABLE_401_CODES` is modified; new code is added *alongside*.
- existing tests: not weakened — fixtures gain the token; assertions stay.
- full suites run in the final phase, pre-existing failures called out, never silently fixed.

---

# THE PLAN

> **Verification discipline for every phase:** phases are independently committable and leave the repo working (backend: `uv run pytest tests/unit -q`; frontend: `npm run typecheck && npm test`). The **final** phase runs the *full* four-command suite (see Phase 6).

---

## Phase B1 — Backend config + dependency promotion (independent commit)

**Goal:** `Settings` gains a required `TURNSTILE_SECRET_KEY` that refuses to boot on the placeholder — mirroring `TOTP_ENCRYPTION_KEY` exactly — and `httpx` moves from `dev` to runtime deps.

### `backend/app/core/config.py`

**BEFORE** (L64 in the current tree):
```python
    totp_encryption_key: str = Field(validation_alias="TOTP_ENCRYPTION_KEY")
```

**AFTER** (append below that block, with the same comment style):
```python
    # Cloudflare Turnstile secret (siteverify is called server-side on register
    # and login). SAME RULE AS TOTP: required, no default, and the app refuses
    # to start on the placeholder from .env.example. A defaulted or placeholder
    # secret key would silently verify nothing (or every) captcha.
    turnstile_secret_key: str = Field(validation_alias="TURNSTILE_SECRET_KEY")
```

and, under `_totp_key_must_be_a_fernet_key` (L114–137), a second validator:

**BEFORE** (L137):
```python
        return value
```
**AFTER**:
```python
    @field_validator("turnstile_secret_key")
    @classmethod
    def _turnstile_key_is_not_a_placeholder(cls, value: str) -> str:
        # Same refusal style as the TOTP key: the two keys have different
        # formats (Turnstile secrets are opaque), so this checks the placeholder
        # rather than pretending to validate a format we could never pin down.
        if value.startswith("CHANGE_ME"):
            raise ValueError(
                "TURNSTILE_SECRET_KEY is still the placeholder from .env.example. "
                "Create the widget in the Cloudflare dashboard, copy its secret "
                "key into backend/.env, and never commit it."
            )
        return value
```

> Note: the validator deliberately does NOT refuse a missing value at boot in a separate production rule — `Field(...)` (no default) already makes Settings() fail fast if the env var is absent, and the production-model validator (`_production_is_actually_hardened`) needs no new branch because *every* environment must have it.

### `backend/pyproject.toml`

**BEFORE** (L11–24 and L26–28):
```toml
dependencies = [
    "fastapi>=0.111.0",
    ...
    "qrcode[pil]>=7.4.0",
]
...
dev = [
    "pytest>=8.2.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
    "ruff>=0.5.0",
]
```

**AFTER** — move the existing line (append to main deps, remove from dev):
```toml
dependencies = [
    ...
    "qrcode[pil]>=7.4.0",
    # Runtime HTTP client for the server-side Cloudflare siteverify call
    # (moved here from dev; the package was already pinned by devTools).
    "httpx>=0.27.0",
]
...
dev = [
    "pytest>=8.2.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.5.0",
]
```

Follow the repo's own regeneration step (`backend/README.md` L80–82) — **this is a requirement, not advice**:
```bash
uv lock
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
uv export --format requirements-txt --no-hashes --no-emit-project --extra dev -o requirements-dev.txt
```

### `backend/.env.example`

**BEFORE** (L52–56, the 2FA/TOTP block):
```
# ─────────────── 2FA / TOTP ───────────────
...
TOTP_ENCRYPTION_KEY=CHANGE_ME_generate_with_fernet
```

**AFTER** — add after the TOTP block:
```
# ─────────────── Cloudflare Turnstile (CAPTCHA) ───────────────
# Secret key for the SERVER-SIDE siteverify call on /auth/register and
# /auth/login. NEVER expose this to the browser — it has no NEXT_PUBLIC_ twin.
# Create the widget in the Cloudflare dashboard and paste its SECRET key here
# (the site key goes in frontend/.env.local as NEXT_PUBLIC_TURNSTILE_SITE_KEY).
TURNSTILE_SECRET_KEY=CHANGE_ME_create_in_cloudflare_dashboard
```

### `backend/tests/unit/conftest.py` — the `_TEST_ENV` dict MUST gain the key (missing from Rev 1; Phase 6 would have caught it)

`tests/unit/conftest.py` sets `_TEST_ENV` into `os.environ` at **import time** (its docstring: "must run on a fork, in a fresh clone, and in CI without secrets"), because `get_settings()` is lru_cached and reads the environment on first construction. The moment `turnstile_secret_key` becomes a required no-default field, every unit test that transitively constructs `Settings()` — `security.py`, `totp.py`, `config.py` itself, which is almost every unit module — throws `ValidationError` on any machine without the env var. Without this sub-step, `uv run pytest tests/unit -q` is red immediately after Phase B1 lands.

**BEFORE (L31–35, the tail of the `_TEST_ENV` dict):**
```python
    # The default cost is deliberately expensive; these tests hash repeatedly and
    # are asserting behaviour, not tuning.
    "ARGON2_TIME_COST": "1",
    "ARGON2_MEMORY_COST": "8192",
    "ARGON2_PARALLELISM": "1",
}
```

**AFTER — append inside the dict (and update the file's docstring listing what it fakes):**
```python
    "ARGON2_PARALLELISM": "1",
    # Fake Turnstile secret for tests/unit only. The config validator only
    # refuses a CHANGE_ME placeholder — never start with that prefix — and the
    # value is otherwise opaque, so a fixed string is as real as it needs to be.
    # No unit test ever calls siteverify; this exists only so Settings validates.
    "TURNSTILE_SECRET_KEY": "0" * 40,
}
```

**Commit (imperative, < 72):**
```
chore(be): promote httpx and add TURNSTILE_SECRET_KEY settings

- move httpx>=0.27.0 from dev to runtime deps for the siteverify call
- add required no-default TURNSTILE_SECRET_KEY, refusing the placeholder
- add a fake TURNSTILE_SECRET_KEY to tests/unit/conftest.py _TEST_ENV so
  Settings reruns on a fresh clone / CI without a .env (Rev 2 fix)
- regenerate uv.lock and both pip exports (backend README rule)
```

---

## Phase B2 — Verification seam, error, schemas, service wiring

### B2.1 New file `backend/app/auth/turnstile.py`

```python
"""
Server-side Turnstile verification (register/login only).

NEVER RETURN the raw `error-codes` to a client: they name Cloudflare internals
and this repo's rule is that a caller never sees more than the envelope
(errors.py `_unhandled_error_response`). They are logged and the client gets
one generic `CAPTCHA_FAILED`.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("edubridge.turnstile")

# Verified against Cloudflare docs at implementation time; the URL below is the
# documented one as of the last check.
SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile_token(token: str) -> bool:
    """
    POST the widget's token to siteverify as application/x-www-form-urlencoded.
    Returns True only when the response has `success: true`.

    FAIL-CLOSED: a network failure or a malformed response counts as a
    failure. The consequence of refusing a real visitor is a re-check; the
    consequence of accepting a bot is the thing the captcha exists to stop,
    and on this endpoint that is credential stuffing against minors' accounts.
    """
    settings = get_settings()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                SITEVERIFY_URL,
                data={
                    "secret": settings.turnstile_secret_key,
                    "response": token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        # ValueError covers a non-JSON body. Logged, client never sees why.
        logger.warning("turnstile siteverify failed to contact the provider")
        return False

    success = payload.get("success")
    if not isinstance(success, bool):
        logger.warning("turnstile siteverify returned an unexpected payload")
        return False

    if not success:
        # error-codes is a list of Cloudflare codes; log only.
        logger.error("turnstile rejected token: %s", payload.get("error-codes"))
        return False
    return True
```

> The seam to mock in tests is the **function** (`verify_turnstile_token`), not `httpx` — matching how `never_send_real_email` patches `get_email_sender`. Unit tests may additionally patch `httpx.Client` directly to exercise the parsing branches without any socket.

### 2.2 `backend/app/core/errors.py` — new factory

**BEFORE** (where the family facteurs sit, e.g. partition after `rate_limited` L56–58):
```python
def rate_limited(message: str = "Too many requests. Please slow down.") -> AppError:
    return AppError(code="RATE_LIMITED", message=message, status_code=429)
```

**AFTER** — add in the same style with a comment:
```python
def captcha_failed(message: str = "Please complete the security check again.") -> AppError:
    # 400, not 403: the request body carried a token that failed verification,
    # exactly like VALIDATION_ERROR is a 400 for a body that failed validation.
    # The code — not the status — is what the client branches on, and this code
    # is new, so a client that does not know it renders the generic state
    # safely (ERROR_CODES additions in the frontend phase).
    return AppError(code="CAPTCHA_FAILED", message=message, status_code=400)
```

### 2.3 `backend/app/auth/schemas.py`

**BEFORE — RegisterRequest (L35–47)** and **LoginRequest (L120–122)**:
```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    ...
```
```python
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
```

**AFTER — both get the same field:**
```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    # Required Cloudflare Turnstile token (register + login only).
    turnstile_token: str = Field(min_length=1)
    ...
```
```python
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Required Cloudflare Turnstile token; a missing or empty value is a 400
    # VALIDATION_ERROR like any other missing required field.
    turnstile_token: str = Field(min_length=1)
```

> Pydantic makes the field **required** — a missing/empty token is auto-`400 VALIDATION_ERROR` with `details.fields.turnstile_token`, which the frontend already knows how to render. The `captcha_failed()` factory only fires for a *present-but-rejected* token. This split is deliberate: "client sent no token" and "client sent a token Cloudflare rejected" are different failures, and the second one must be shown with a retry instruction while the first is a client bug.

### 2.4 `backend/app/auth/service.py` — the two hooks

**THE MOST IMPORTANT ORDERING DECISION IN THIS TASK (stated explicitly):** in `login()`, `verify_turnstile_token(payload.turnstile_token)` must run **before** the `app.lookup_user_for_login` query **and before** the `verify_password` / `_dummy_password_hash()` branch. `login()` is carefully built so an unknown email costs the same as a wrong password; a captcha check placed *after* that branch would add a measurable timing difference between "valid token, wrong password" and "valid token, account missing" — enumerating addresses by delay, violating the timing side of tdd.md §6.11. Putting the captcha check *first* makes it a constant cost paid by EVERY caller regardless of anything the username reveals; both branches then run under identical prior work.

**BEFORE — service.py L96 (register, first line):**
```python
def register(db: Session, payload: RegisterRequest) -> dict:
    # Two DIFFERENT failures, two different codes. ...
    payload.validate_required_student_fields()
```

**AFTER — first two statements of `register()`:**
```python
def register(db: Session, payload: RegisterRequest) -> dict:
    # Captcha BEFORE any schema/DB work and before issuing anything: a client
    # asserting "I solved the captcha" is never trusted alone (rule 3c), and a
    # rejected token must waste no account machinery and, especially, no hash.
    if not verify_turnstile_token(payload.turnstile_token):
        raise captcha_failed()

    payload.validate_required_student_fields()
```

**BEFORE — service.py (login, L275–277, first executable statement):**
```python
    row = (
        db.execute(
            text(
                "SELECT id, password_hash, status, email_verified_at "
                "FROM app.lookup_user_for_login(:email)"
```

**AFTER — the same line becomes the SECOND statement:**
```python
    # 1) CAPTCHA, FIRST — before the lookup and before the dummy-hash branch,
    #    so the captcha is a constant cost for every account and never tells
    #    a caller whether an address exists (tdd.md §6.11, timing side).
    if not verify_turnstile_token(payload.turnstile_token):
        raise captcha_failed()

    # 2) ... then the existing lookup.
    row = (
        db.execute(
            text(
                "SELECT id, password_hash, status, email_verified_at "
                "FROM app.lookup_user_for_login(:email)"
```

**Imports** added to service.py imports block: `from app.auth.turnstile import verify_turnstile_token` / `from app.core.errors import captcha_failed`. (Rev 2: the function exported from `turnstile.py` is `verify_turnstile_token` — the plan's Rev-1 draft said `verify_actual_token`, which would have been an ImportError at runtime.)

### 2.5 Commit

```
feat(be): require Turnstile captcha on register and login

- verify the client token against Cloudflare siteverify before any
  database work in both service functions
- login checks the captcha before the constant-time dummy-hash branch
  so an unknown email and a wrong password still cost the same
- add CAPTCHA_FAILED (400) to the error catalogue
- schema: turnstile_token is required on RegisterRequest and LoginRequest
```

---

## Phase B3 — Backend tests (the suite must never touch Cloudflare)

### 3.1 `backend/tests/integration/conftest.py` — the `never_call_turnstile` fixture

The exact precedent is `never_send_real_email` (L77–102): autouse, patches the **seam** (not the env), because `get_settings()` is `lru_cache`d and a real env poke would be too late.

**BEFORE — end of conftest, after `never_send_real_email` (L103):**
```python
    monkeypatch.setattr(email_module, "get_email_sender", email_module.LoggingEmailSender)
    yield
    email_module.drain_pending_emails()
```

**AFTER — a new autouse fixture right below it:**
```python
@pytest.fixture(autouse=True)
def never_call_turnstile(monkeypatch):
    """
    THE SUITE MUST NOT TALK TO CHALLENGES.CLOUDFLARE.COM.

    Same rule as `never_send_real_email`: a developer .env with a real
    TURNSTILE_SECRET_KEY and a token in a test body would fire a live HTTP
    call from CI. Patch the verify seam so every verification PASSES; the
    captcha-failure paths are tested by explicitly re-patching it to a
    rejecting stub (see test_turnstile.py).
    """
    import app.auth.turnstile as turnstile_module

    monkeypatch.setattr(turnstile_module, "verify_turnstile_token", lambda _token: True)
    yield


@pytest.fixture
def valid_turnstile_token() -> str:
    """The token value supplied by tests; the autouse fixture accepts anything."""
    return "test-turnstile-token"
```

### 3.2 Existing integration tests — fixtures updated, assertions untouched

Every test that posts `"/api/auth/register"` or `"/api/auth/login"` JSON, or constructs a schema object directly, gets the token field. **No assertion is weakened — only the *input* is extended** (rule 5).

- `backend/tests/integration/test_register.py` — each `json=payload` in L11/L35/L51/L71/L82/L108/L132: add `"turnstile_token": "test-turnstile-token"`. (Best done via a small local helper or a constant in conftest, so it is one line.)
- `backend/tests/integration/test_auth_flows.py` — L25/L32/L43/L55 `json={"email": …, "password": …}` → `json={"email": …, "password": …, "turnstile_token": "test-turnstile-token"}`.
- `backend/tests/integration/test_login_discriminator.py` — L90/L104/L115/L132/L144/L159 `LoginRequest(email=…, password=PASSWORD)` → add `turnstile_token=TURNSTILE_TOKEN` (import a constant from conftest or define at top of the file).
- `backend/tests/integration/test_email_password.py` — L192 login call gets the field.
- `backend/tests/integration/test_refresh_flow.py` — L20/L117 register payloads get the field.

> Because `never_call_turnstile` auto-accepts any token, all these tests behave exactly as before. The change is mechanical and asserted by the suite staying green.

### 3.3 New files

**`backend/tests/unit/test_turnstile.py`** — no network, no DB:
- `verify_turnstile_token` returns True when the mocked `httpx.Client.post` yields `{"success": true}`.
- Returns False when `{"success": false, "error-codes": ["timeout”]}` — and **asserts the codes are logged, not raised** (via `caplog`).
- Returns False on `raise_for_status` (non-2xx), on a non-JSON body, on `payload["success"]` not being bool.
- Ordering test for `login()`: patch `verify_turnstile_token` to a spy and assert it is **called once and before** the password/hash machinery for both a known and an unknown email (use `monkeypatch` + `unittest.mock` call order, with `app.auth.service.verify_password` also spied).
- Config test (can live in `test_security.py` or here): `Settings()` with `TURNSTILE_SECRET_KEY=CHANGE_ME_…` raises `ValidationError` naming the field.

**`backend/tests/integration/test_turnstile.py`**:
- `test_register_with_rejected_captcha_is_400` (patch seam → `False`): `/api/auth/register` with a valid body → `400 CAPTCHA_FAILED`; **assert no user row exists** afterwards (proves no account machinery ran).
- `test_login_with_rejected_captcha_is_400` (seam → `False`): `/api/auth/login` with **an unknown email** → `400 CAPTCHA_FAILED`, NOT `401 UNAUTHENTICATED` — this is the observable contract-level proof of the ordering rule.
- `test_missing_token_is_validation_error`: omit `turnstile_token` → `400 VALIDATION_ERROR` with `details.fields.turnstile_token`.
- `test_empty_token_is_validation_error`: `"turnstile_token": ""` → same.
- `test_captcha_success_still_authenticates`: seam → `True`, existing happy-path login asserts.
- `test_error_body_never_leaks_codes`: seam → a stub raising after logging the codes; assert the response body contains neither `error-codes` nor the Cloudflare code string.

### 3.4 Commit

```
test(be): isolate the suite from the real Turnstile service

- autouse never_call_turnstile fixture patches the verify seam, mirroring
  never_send_real_email so pytest never visits challenges.cloudflare.com
- extend every register/login fixture with a test token; no assertion
  weakened, no test skipped
- cover ordering, missing/empty token, and the no-leak response rule
```

---

## Phase F1 — Frontend: env, types, widget component, CSP

### 4.1 `frontend/.env.example` — client-exposed *site* key only

**BEFORE** (bottom, L16–17):
```
# Server-side only (NOT exposed to the browser)
BACKEND_INTERNAL_URL=http://localhost:8000
```

**AFTER** — append a public-key block (and keep the server-only note):
```
# Cloudflare Turnstile — PUBLIC site key (safe to expose in the browser; the
# SECRET key lives only in backend/.env as TURNSTILE_SECRET_KEY).
# Put the real site key in .env.local (gitignored). The widget renders only
# when a value is present.
NEXT_PUBLIC_TURNSTILE_SITE_KEY=
```

> The human's `frontend/.env.local` (gitignored) will hold the real site key given at hand-over (`0x4AAAAAAEKhg-Qtr2h7j9ek`). This plan does not require a provisioning step — just the documentation above literal.

### 4.2 `frontend/lib/api/types.ts` — contract mirror

**BEFORE** (L61–70, L82):
```ts
export type RegisterRequest = {
  email: string
  password: string
  full_name: string
  role: Exclude<Role, 'admin'>
  // Students only.
  board?: BoardCode
  class_level?: number
  student_group?: StudentGroup
  medium?: Medium
  language_pref?: ApiLanguage
}

export type LoginRequest = { email: string; password: string }
```

**AFTER** — add the token, mirroring the backend schema exactly:
```ts
export type RegisterRequest = {
  email: string
  password: string
  full_name: string
  role: Exclude<Role, 'admin'>
  // Required everywhere since the Turnstile rollout: the client proves
  // a human solved the widget before the server will touch the account.
  turnstile_token: string
  // Students only.
  board?: BoardCode
  class_level?: number
  student_group?: StudentGroup
  medium?: Medium
  language_pref?: ApiLanguage
}

export type LoginRequest = { email: string; password: string; turnstile_token: string }
```

### 4.3 New component `frontend/components/auth/Turnstile.tsx`

**Hand-rolled, not a wrapper package.** Decision and reasons (rule 5.3):
- The repo already **prefers no third-party dependency on-top** of supply chain curation (see `package.json` `overrides` comment: the team adds packages only under restraint and pins hotfixes where they must).
- The Cloudflare API surface we use is one script load + `render`/`reset`/`remove`. A wrapper package (`@marsidev/react-turnstile` etc.) adds a dependency, a peer-versions surface, and a maintainer to trust, for fewer than 40 lines. It is also more likely to be *rejected* in review on the supply-chain precedent than accepted.
- Hand-rolled gives exact control over load (only on the three forms — matches the app's own "load the Urdu font only for `ur`" precedent, `tdd.md §3.10`), CSP cohabitation, and a trivial mock for tests via `window.turnstile`.

Component contract:
```tsx
'use client'

// Loads https://challenges.cloudflare.com/turnstile/v0/api.js once (module-level
// guard against double-inject) the FIRST time a form using it mounts; renders
// the widget into a container ref; calls onVerify(token) when a fresh token is
// produced, onError() if Cloudflare refuses. onExpire is wired so a token that
// lapses mid-session clears itself instead of being submitted stale.

type Props = {
  onVerify: (token: string) => void
  onExpire?: () => void
  /** Bumping this value imperatively resets the widget (see forms). */
  resetNonce?: number
  className?: string
}

declare global {
  interface Window { turnstile?: { render: fn; reset: fn; remove: fn } }
}
```

Implementation notes (not code-in-plan detail): script url derived at runtime from the documented `…/api.js?render=explicit` — auto-renders by default; a container div with height ~64 to avoid layout shift; `language` passed from `useLocale()` mapped to Cloudflare's `ur` for `ur`, default `en` for both other locales (documented as a localization pass — verified text/directionality at implementation time).

**CSP — `frontend/next.config.mjs`**

**BEFORE** (L65–84):
```js
  value: [
    ...
    `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''}`,
    "style-src 'self' 'unsafe-inline'",
    ...
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ''}${isDev ? ' ws: wss:' : ''}`,
    "frame-ancestors 'none'",
```

**AFTER** — add the Turnstile origins to `script-src` and `connect-src`, and a new `frame-src`. Keep the existing comment discipline (explain *why*, not just *what*):
```js
    // Turnstile loads its challenge script from challenges.cloudflare.com and
    // renders inside a Cloudflare-served iframe — so script-src, the
    // otherwise-absent frame-src, AND connect-src must admit it, or the widget
    // is blocked by the very policy that protects these forms. All three
    // directives are in Cloudflare's own references (script-src + frame-src in
    // the CSP reference; connect-src because the widget's orchestration code
    // fetches from this origin, per the widget docs and production configs
    // such as Storefront). No other third-party origin is allowed.
    `script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com${isDev ? " 'unsafe-eval'" : ''}`,
    "style-src 'self' 'unsafe-inline'",
    ...
    `connect-src 'self' https://challenges.cloudflare.com${apiOrigin ? ` ${apiOrigin}` : ''}${isDev ? ' ws: wss:' : ''}`,
    "frame-src https://challenges.cloudflare.com",
    "frame-ancestors 'none'",
```

> `frame-ancestors 'none'` is unchanged — that directive governs *our* page being framed; `frame-src` governs what our page may frame. Both coexist.
>
> **Rev 2 note — do not stop at "config looks right".** Cloudflare's CSP reference lists `script-src` + `frame-src` for standard (non-pre-clearance) mode, but the widget's own doc says "your application will connect to this origin", and the widget's JS can make its own fetch calls from the parent page. The three-`src` allow-list above is therefore the *conservative* setup. **Verification is a Phase-6 task, not a code change:** load the actual login/signup pages in a browser (running against the real site key + secret) with the CSP applied and watch the DevTools console for any `challenges.cloudflare.com` violation across *all* directives; adjust the allow-list only in response to a real violation, and record the outcome in the Phase-6 report.

### 4.4 Commit

```
feat(fe): add Turnstile widget and its CSP entries

- hand-rolled component loading Cloudflare's script once and rendering
  explicitly; resetNonce prop for imperative reset
- add NEXT_PUBLIC_TURNSTILE_SITE_KEY to .env.example (public key only)
- widen script-src and connect-src for challenges.cloudflare.com and add
  frame-src; the widget iframe and its own fetches need all three
```

---

## Phase F2 — Frontend wiring: three forms, errors, mock, tests, i18n

### 5.1 `frontend/lib/api/errors.ts` — allow-list

**BEFORE** (L9–33):
```ts
export const ERROR_CODES = [
  'VALIDATION_ERROR',
  ...
  'MODEL_UNAVAILABLE',
] as const
```

**AFTER** — new entry between `INVALID_CLASS_GROUP` and the tail (exact position is cosmetic; keep the array literately ordered):
```ts
  'INVALID_CLASS_GROUP',
  // Turnstile token rejected by Cloudflare siteverify. 400, but NOT
  // VALIDATION_ERROR: the client must reset the widget and re-solve, because
  // the token is single-use and may be consumed by the failed POST.
  'CAPTCHA_FAILED',
  'SELF_LINK_FORBIDDEN',
```

> No change to `isRefreshableAuthError`/`REFRESHABLE_401_CODES`: `CAPTCHA_FAILED` is a **400**, is not in the 401 allow-list, and the `login()` endpoint call already carries `noRetry: true` (see §5.6) — the retry logic is untouched, the new code is simply *added alongside* (rule 4).

### 5.2 `frontend/components/auth/Turnstile.tsx` — reset semantics (spelled out, because it is the most user-visible failure mode)

- The widget holds **one token at a time**. A token is **single-use** (siteverify consumes it) and **short-lived** (Cloudflare-documented ~300s).
- The form keeps `const [captchaToken, setCaptchaToken] = useState<string | null>(null)`.
- `onVerify={setCaptchaToken}`; `onExpire={() => { setCaptchaToken(null); }}` — token expiry must block a stale submit.
- **Reset after EVERY failed submit**: in the submit catch (all branches), call `setCaptchaToken(null)` **and** bump the reset nonce → parent renders `<Turnstile resetNonce={n} …>`; the component, inside a `useEffect` on `resetNonce`, calls `window.turnstile.reset(widgetId)` and clears the token. The submit button stays disabled until `onVerify` fires again. This is what prevents "button re-enables with a dead token and silently blocks every subsequent submit".
- The token is **cleared for both login and signup on failure**, and **not** cleared on success-navigation (we're leaving the page anyway).

### 5.3 `LoginForm.tsx` wiring

**BEFORE** (L40–61):
```tsx
  const [rateLimited, setRetryAtMs] = ...
  const canSubmit = email.trim() !== '' && password !== '' && !submitting && !rateLimited

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    ...
    try {
      const result = await login({ email: email.trim(), password })
```

**AFTER:**
```tsx
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaNonce, setCaptchaNonce] = useState(0)
  const canSubmit =
    email.trim() !== '' && password !== '' && captchaToken !== null && !submitting && !rateLimited

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    ...
    try {
      const result = await login({ email: email.trim(), password, turnstile_token: captchaToken ?? '' })
```

Insert between the password field and the submit button:
```tsx
<Turnstile onVerify={setCaptchaToken} onExpired={() => setCaptchaToken(null)} resetNonce={captchaNonce} />
```

In the `catch` block, before re-arming the button — **first lines of the catch** (all branches):
```tsx
    } catch (error) {
      // Any failed submit means the siteverify consumed the token. Drop it and
      // force a fresh solve; never re-enable with a dead token.
      setCaptchaToken(null)
      setCaptchaNonce((n) => n + 1)
      setSubmitting(false)
```

Shown the SECURITY DEMO flow: `LoginForm.tsx` already has no `noRetry` — it **does** pass `noRetry: true` via `endpoints.ts` (L160–162); no change to either file is needed for that property (see §5.6).

### 5.4 `StudentSignupForm.tsx` wiring (3 steps)

**BEFORE** (L13–24, L81–92, L93–133):
```tsx
type Draft = { full_name: string; email: string; password: string; ... }
const basicComplete = draft.full_name.trim() !== '' && draft.email.trim() !== '' && draft.password.length >= 8
...
async function submit() {
  setSubmitting(true); ...
  try {
    await registerAccount({ email: draft.email, password: draft.password, ... })
```

**AFTER** — the widget goes on **step 2 (review)**, since a student only submits from step 2:
```tsx
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaNonce, setCaptchaNonce] = useState(0)
  // gating: the submit button requires a token; per-step "continue" buttons do
  // NOT — the student fills credentials first and hits the captcha at review,
  // keeping the flow's pre-existing gating shape intact.
  const reviewComplete = basicComplete && academicComplete && captchaToken !== null
```
```tsx
  try {
    await registerAccount({
      email: draft.email,
      password: draft.password,
      full_name: draft.full_name,
      turnstile_token: captchaToken ?? '',
      ...
```

Inside the step-2 `section` (after the `dl`):
```tsx
            <Turnstile onVerify={setCaptchaToken} onExpired={() => setCaptchaToken(null)} resetNonce={captchaNonce} />
```

Submit button (step 2) `disabled` becomes `submitting || !basicComplete || !academicComplete || captchaToken === null`. In `submit`'s `catch`, first two lines identical to §5.3: clear token, bump nonce.

### 5.5 `SimpleSignupForm.tsx` wiring

**BEFORE** (L26–53):
```tsx
  const [password, setPassword] = useState('')
  const complete = fullName.trim() !== '' && email.trim() !== '' && password.length >= 8

  async function submit(event: React.FormEvent) {
    ...
    await registerAccount({ email, password, full_name: fullName, role })
```

**AFTER** — same pattern:
```tsx
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaNonce, setCaptchaNonce] = useState(0)
  const complete = fullName.trim() !== '' && email.trim() !== '' && password.length >= 8 && captchaToken !== null
  ...
      await registerAccount({ email, password, full_name: fullName, role, turnstile_token: captchaToken ?? '' })
```
Widget after the password `TextField`, inside the space-y-5 div; catch-block first lines (clear + bump) as in §5.3.

> **Rule-7 check:** none of the three forms' existing logic (validation, gating, error mapping) is *altered* — the captcha token is simply AND-ed into the existing `complete`/`basicComplete` gating and passenger via the request body. Logic in `fields.tsx` (`TextField`, `RadioCards`) is untouched.

### 5.6 noRetry / refresh interaction (checked, not changed)

- `login()` is called with `noRetry: true` (endpoints.ts L61) → `apiFetch` will never run `refreshOnce()` for ANY 401 from login, including a captcha-triggered one.
- `CAPTCHA_FAILED` is a **400** anyway — `isRefreshableAuthError` requires `status === 401`; `REFRESHABLE_401_CODES = {'UNAUTHENTICATED','UNKNOWN'}` — so even absent `noRetry` the code would not refresh.
- The proactive-refresh line (`client.ts` L158) only fires when `getAccessToken() !== null` — on the login/signup pages there is no session; nothing changes.
- **No line in `client.ts` or `errors.ts` touching refresh logic is modified.** (Rule 4 satisfied.)

### 5.7 Mock layer (`frontend/lib/api/mock/index.ts`) — mirrors the contract

**BEFORE** (`POST /auth/register` and `POST /auth/login` read `req.email`, `req.password`):
```ts
    case 'POST /auth/login': {
      const req = body as unknown as LoginRequest
      const user = findByEmail(req.email)
      ...
```

**AFTER** — a single guard at the top of both handlers (mock never verifies the token; the real backend does, and dev mode must behave the same *shape*, not the same security):
```ts
    case 'POST /auth/register': {
      const req = body as unknown as RegisterRequest
      if (typeof req.turnstile_token !== 'string' || req.turnstile_token === '') {
        fail(400, 'VALIDATION_ERROR', { fields: { turnstile_token: 'This field is required.' } })
      }
      ...
```
and same for `POST /auth/login`. Tests may also use `setMockScenario('CAPTCHA_FAILED@login')` if useful (the `applyScenario` switch gets a case mapping to `400, 'CAPTCHA_FAILED'` — optional, but it makes the client state locally demoable).

### 5.8 i18n — three locale files, sync

Namespaces used by the forms; add the following keys to **each of** `frontend/messages/{en,ur,ur-Latn}.json` (§signup.common and §auth namespace):

- `auth.turnstile` (label rendered above the widget on the login form — the widget itself draws its own button/interstitial): `{ "label": "Security check" }`
- `signup.common.turnstileLabel`: `"Security check"`
- `auth.errors.captchaFailed` and `signup.errors.captchaFailed`: `"The security check did not go through. Please try again."` (ur: `"سیکیورٹی چیک مکمل نہیں ہوا، براہ کرم دوبارہ کوشش کریں۔"`, ur-Latn: `"Security check mukammal nahi hua, phir se koshish karain."` — short copy, human-tuned on review as the repo already does for all messages).

> New keys are new strings; no existing key is touched, keeping the confirm-password branch's `signup.common.confirmPassword/mismatch` (if merged later) collision-free (rule 1).

### 5.9 Frontend tests (no widget internals in jsdom by default)

- `frontend/components/auth/Turnstile.test.tsx` (new): with a stubbed `window.turnstile`, assert: `onVerify` is called after `render`'; `resetNonce` bump calls `reset`; `onExpired` clears; the script is injected only once (module guard).
- `LoginForm.test.tsx` (update): the form mocks `@/lib/api/endpoints` already; add a module mock `vi.mock('@/components/auth/Turnstile', () => ({ Turnstile: (p: …) => <button data-testid="turnstile" onClick={() => p.onVerify?.('mock-token')} /> }))`, then: assert `Sign in` is disabled until the fake widget token is issued, submits with `turnstile_token: 'mock-token'` (assert on the `login` spy args), and after a failed submit (mock `login` rejects CAPTCHA_FAILED) the widget is reset (the fake re-issues a new token → the spy receives `registerAccount`/`login` again with a *fresh* token).
- `StudentSignupForm.test.tsx` and the (currently missing) `SimpleSignupForm.test.tsx` — same mock, extend/gate assertions: step-2 submit disabled until token; mismatch: forms keep their existing assertions untouched (regression).

### 5.10 Commit

```
feat(fe): gate login and signup on a Turnstile token

- captcha token AND-ed into existing canSubmit/complete gating on the
  three forms; submitted field turnstile_token mirroring the schema
- every failed submit clears and resets the widget (tokens are single-use)
- CAPTCHA_FAILED enters ERROR_CODES; badge only spins, never canned
- mock layer validates presence; i18n keys added in all three locales
```

---

## Phase 6 — Full-suite verification (the final phase; nothing else)

**Before this change**, on `main`, both suites are believed green (per the repo's CI convention). Run and **record** — before AND after the change:

```bash
cd backend && uv run pytest tests/unit/ -q && uv run pytest tests/integration/ -q
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

**Contract for the executor:**
- `tests/unit`, `tests/integration`, `typecheck`, `lint`, `test`, `build` must each be green **after** the change.
- If any is red **before** the change (pre-existing), record it in the PR's description as a pre-existing failure, do **not** silently fix it as a drive-by inside this plan, and do not attribute it to this work. File it as a follow-up issue.
- **Widget/CSP live check (Rev 2 addition — a test suite cannot see CSP violations):** in a dev server whose CSP actually applies (dev headers from `next.config.mjs` are active), load the login and both signup pages with the real site key in `frontend/.env.local`, solve the widget, and watch DevTools console for CSP violations against `challenges.cloudflare.com` (script-src, frame-src, connect-src). A clean console + a token produced on all three forms is the *evidence*; record it in the Phase-6 report. This is also the first point where the plan's `connect-src` decision is truly exercised, since units/jsdom cannot fetch the widget.
- The plan's changes must not be considered done until this phase's report is attached to the PR.

**Commit for the verification run** (if a commit is wanted for the trace):
```
chore: record full-suite verification for the Turnstile change

- backend unit + integration, frontend typecheck, lint, tests, build
  all green on HEAD after the captcha change
```

---

## Definition of Done (cross-check against the task's contract)

- [x] Both `register()` and `login()` return `CAPTCHA_FAILED` (400) before any account/session logic runs (ordering spelled out and covered by tests).
- [x] Server-side verification against `challenges.cloudflare.com/turnstile/v0/siteverify` is the only trust path.
- [x] Constant-time login preserved — no branch between known and unknown address before the hash; unit test pins the order.
- [x] The suite never calls Cloudflare: never_`fixture` autouse + no test keys used.
- [x] Client auto-resets the widget on any failed submit; fresh token required before submit re-enables.
- [x] Secret key server-only; `NEXT_PUBLIC_` gated to the site key.
- [x] `ruff check`, both suites, `npm run typecheck`, lint, build green (Phase 6 trace).
- [x] No out-of-scope endpoint (reset/2fa/guardian) gained captcha.

---

## ASSUMPTIONS (stated explicitly)

1. **Egress:** Network egress from the backend to `challenges.cloudflare.com` is assumed permitted — `infra/.env.example`/`docker-compose` don't currently document an allowlist (confirmed by reading them? *not read in this plan* — flag it in Open Questions 1, since the repo docs don't describe egress policy at all, the assumption is permissive).
2. **Contract state:** `feature/confirm-password` is NOT merged (verified by `git merge-base`). Both cases are supported: if it merges before execution, Turnstile lands additively on the same forms with no behavior change to the confirm field.
3. **Siteverify shape:** `success` + `error-codes` are read; current shape and test-key values re-verified from docs at execution time (rule 2).
4. **Secret placement:** `TURNSTILE_SECRET_KEY` will have been placed in `backend/.env` by a human before Phase B1 runs (the prompt states it is already there).
5. **Frontend site key:** real key goes in `frontend/.env.local` (gitignored); dev default blank → the widget render logic must handle blank (Plan the widget to render an explicit "security check unconfigured" state only in dev, or fail the build to remind — **decision:** blank key → component renders `null`, and the form's token stays null so submit is disabled. Because mock mode is the default in dev, forms still exercise everything else. Document this behavior in the widget's comment).
6. **One widget per form.** No shared document header/script caching needed beyond the module guard.

---

## OPEN QUESTIONS (deliberately left open — answered inline with options, not silently decided)

1. **Egress allowlist.** `backend/.env.example` and `infra/*` never mention per-host egress rules; production deployment will hit `challenges.cloudflare.com:443`. If a network policy exists anywhere, confirm and document the allow; otherwise the first production deploy will fail closed (which is the safe failure, but it will fail). — Flagged, not implemented.

2. **Rate-limit bucket for a failed captcha.** Recommendation: **reuse** the existing `LOGIN_LIMIT` (10/60s) and `REGISTER_LIMIT` (5/300s). Rationale: `enforce()` in `routes.py` runs **before** the service call, so *every* request — including captcha-rejected ones — already consumes the bucket; adding a separate "captcha-fail" bucket would allow an attacker to burn captcha failures without touching the login/register bucket (they're already burning it anyway) and adds a second counter to tune with the same abusers. If the team prefers an independent control (to, e.g., raise the register cap while captcha-verification keeps failing), add `CAPTCHA_FAIL_LIMIT` next to `GUARDIAN_*` with the same `Limit` table style. **Open; default assumption = share.**

3. **Widget loading: hand-rolled or wrapper package.** Hand-rolled (see §4.3 why). Trade-off named: hand-rolled carries the risk that Cloudflare renames the script URL or callback names (docs drift); a package seals that behind its own maintenance, but adds a dependency the repo has historically avoided (overrides precedent). If the team prefers a package, specifying `@marsidev/react-turnstile@2` and accepting it into `dependencies` is an explicit alternative. **Open; default = hand-rolled.**

4. **Team sign-off on the shared contract.** `RegisterRequest`/`LoginRequest` are used by (a) the 2FA/email/password owner (Muneeb), (b) the guardian-flow owner (Mujtaba), (c) any future endpoint. Adding a required field is breaking for un-updated callers. Before merging: post the schema diff in the team channel/PR + adjust instructions on dependencies; both owners confirm no in-flight branch constructs `RegisterRequest`/`LoginRequest` without the field (the repo itself verified in this plan — `test_login_discriminator` etc. are covered, but a teammate in-flight branch is not). **Open — sign-off required.**

5. **Fail-closed on provider outage.** The implementation fails closed (network error → `CAPTCHA_FAILED`, §B2.1). Alternative is fail-open with a circuit breaker + admin alert; trade-off named: fail-open risks bot traffic passing when Cloudflare drops, closed hands pirated visitors a locked door instead. For a minors-first platform, closed is the defensible default, but the ops team may decide once egress monitoring exists — their not-to-be-claimed-elsewhere action item.

6. **Widget refresh cadence.** Turnstile's `refresh="auto/manual"` attribute — recommend auto (a fresh token is always ready when the form is completed) but fixes "fresh token at submit time" behavior which interacts with visual load; consciously left as a widget-attribute value-tweak rather than a code decision in this plan.

7. **`NEXT_PUBLIC_TURNSTILE_SITE_KEY` empty in `mock` mode.** Recommend the widget renders nothing and the form gates on the key; in mock mode no captcha is expected; in live mode a missing key must keep the form locked (fail-locked) until the human adds it to `.env.local`. No silent fallback that would submit captcha-less — note as a documented behavior, open on whether a visible "Security check not set up" banner is desired in dev builds.

---

## Revision log

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-08-09 | Initial plan after reading the mandated files; stress passes 1 & 2 folded in; branch state for confirm-password verified. |
| 2 | 2026-08-09 | Team review fixes: (a) Phase B1 gains `tests/unit/conftest.py` `_TEST_ENV` sub-step — the required config field would otherwise red the whole unit suite on fresh clones/CI; (b) corrected the B2.4 import name to `verify_turnstile_token`; (c) CSP `connect-src` gains `challenges.cloudflare.com` alongside `script-src`/`frame-src`, with a live browser verification item added to Phase 6. |