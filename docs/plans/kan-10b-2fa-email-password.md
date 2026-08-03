# KAN-10b — 2FA Enrolment/Challenge, Email Verification & Password Reset

**Branch:** `feature/KAN-10b-2fa-email-password`  
**Author:** Abdul Muneeb (BSDSF23A036)  
**Date:** August 3, 2026  
**Source of truth:** `prd.md` v0.3.4 · `tdd.md` v0.3.4 · applied SQL in `supabase/migrations/`  
**Depends on:** KAN-10 (auth core — register, login, refresh, logout, me)

---

## Scope

| Area | Endpoints |
|---|---|
| **A. 2FA Enrolment** | `POST /auth/2fa/enroll`, `POST /auth/2fa/confirm` |
| **B. 2FA Challenge** | `POST /auth/2fa/verify`, `POST /auth/2fa/resend` |
| **C. Email Verification** | `POST /auth/email/verify`, `POST /auth/email/resend` |
| **D. Password Reset** | `POST /auth/password/forgot`, `POST /auth/password/reset` |
| **E. Backup Code Regeneration** | `POST /auth/2fa/backup-codes` |

**Out of scope:** RBAC deps, guardian invite/confirm, Class 9–10 gate (Mujtaba) · frontend (Yahya) · `GET /subscription` and `POST /subscription/select` (unowned — flagged, not built).

---

## Answers to §14.4 Open Questions

### Finding 1 — No factor switching mid-challenge

**No new endpoint.** `/2fa/resend` re-sends email OTP only for users enrolled in `email_otp`. A TOTP-enrolled user who cannot access their authenticator uses a **backup code** (already issued during enrolment) as the sole alternative. The frontend already renders backup-code as the only alternative factor.

If a future decision adds factor switching, it needs a new endpoint (`POST /auth/2fa/switch-method`). This card does not create one.

### Finding 2 — Enrolment has no resend

**Re-calling `POST /auth/2fa/enroll` IS the resend.** For TOTP it generates a fresh secret/QR (the old pending secret is overwritten by the upsert). For email_otp it re-sends the code. A per-IP rate limit on the `2fa_enroll` bucket (3 requests per 5 minutes) prevents abuse. The `enrollment_token` is only consumed by `/2fa/confirm` on success.

### Finding 3 — `/auth/login` 401 must not be retried

Already resolved in the frontend (`noRetry` flag in `endpoints.ts`). No backend change.

### Finding 4 — email/verify idempotency

**Decision: idempotent success.** When the token was already consumed and `email_verified_at` is set, the server returns `200` with the current onboarding state, a fresh `enrollment_token`, and a scoped `access_token`. A truly unknown or expired token still returns `400 INVALID_TOKEN` or `410 TOKEN_EXPIRED`.

---

## Email Delivery — Resend API

**Provider:** [Resend](https://resend.com) — developer-friendly email API. Free tier: 100 emails/day, 3,000/month.

**Seam design:** an `EmailSender` protocol with two implementations:
- `ResendEmailSender` — sends via Resend API (production)
- `LoggingEmailSender` — logs structured JSON (to, subject, body_length) to Python logger (development/CI)

The factory picks based on `EMAIL_PROVIDER` in settings. Swapping providers means adding one class — no route or service changes.

**New config:** `RESEND_API_KEY`, `EMAIL_FROM` (`noreply@edubridge.ai`), `EMAIL_PROVIDER` (`resend` | `logging`), `APP_BASE_URL`.

**New dependency:** `resend` (Python SDK).

---

## Architecture Decisions

### D1 — All pre-auth flows use SECURITY DEFINER functions

Every endpoint runs before a session exists (no `app.current_user_id()` to satisfy RLS). New `SECURITY DEFINER` functions are added in a dedicated migration. They are narrow — each returns only the columns its flow needs. `get_service_db()` is never used on any request path.

### D2 — Onboarding-scoped access token

`email/verify` returns an access token with JWT claim `type: "onboarding"` instead of `"access"`. The existing `decode_access_token()` only accepts `type: "access"`, so an onboarding token is rejected by the `authenticated` dependency on every business endpoint (including `/auth/me`). This is the enforcement mechanism — no new dependency needed.

### D3 — TOTP secret encryption: Fernet (cryptography library)

`totp_secret_encrypted bytea` stores Fernet ciphertext (AES-128-CBC + HMAC-SHA256). The key lives in `TOTP_ENCRYPTION_KEY` (application config), never in the database. A database dump alone does not yield usable secrets.

### D4 — TOTP generation and verification: `pyotp`

RFC 6238 standard. Generates base32 secrets, produces `otpauth://` URIs, verifies 6-digit codes with ±1 window tolerance.

### D5 — QR SVG generation: `qrcode` library with SvgPathImage factory

Produces valid QR codes as pure SVG — only `<rect>` and `<path>` elements, no `<script>` or external references. Frontend renders as base64 `data:` URI inside `<img>` (`tdd.md` §6.11).

### D6 — Backup codes: 8 alphanumeric, argon2id-hashed, case-insensitive

Characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (excludes ambiguous 0/O/1/I). Compared case-insensitively by uppercasing both sides before hashing. Argon2id with the same parameters as passwords. Single use — `used_at` set on match. All 10 invalidated and regenerated on re-enrolment.

### D7 — Lockout parameters

| Threshold | Lock duration |
|---|---|
| 3 failed attempts | 5 minutes |
| 6 failed attempts | 15 minutes |
| 10 failed attempts | 1 hour |

Lockout is **server-side** in `two_factor_enrollment.locked_until`. A page reload does not reset it. The `423 TWO_FACTOR_LOCKED` response carries `details.locked_until` as ISO timestamp.

### D8 — Email OTP: 6 digits, hashed in `auth_token`, 10-minute TTL

Stored as `kind = 'two_factor_email_otp'`. Previous OTPs revoked before inserting new one. Verified by looking up unrevoked tokens for the user and comparing hashes.

---

## New Dependencies

| Package | Purpose |
|---|---|
| `cryptography` | Fernet encryption for TOTP secret at rest |
| `pyotp` | TOTP secret generation and RFC 6238 verification |
| `qrcode` | QR code SVG generation |
| `resend` | Resend API email delivery |

Added to `pyproject.toml`; `uv lock` regenerates `uv.lock`; `uv export` regenerates `requirements.txt` and `requirements-dev.txt`.

---

## Phases

### Phase 1 — Database Migration: SECURITY DEFINER Functions

**New file:** `supabase/migrations/20260803120000_2fa_email_password_lookups.sql`

Following conventions from `20260802140000`: idempotent `CREATE OR REPLACE`, `REVOKE ALL FROM PUBLIC`, `GRANT EXECUTE TO app_backend`, `search_path = public, pg_temp`.

**15 functions:**

| Function | Purpose |
|---|---|
| `lookup_challenge_token(p_hash, p_kind)` | Look up enrollment/pending token by hash, asserting kind. Returns `(id, user_id, kind, revoked, expires_at)`. |
| `upsert_2fa_enrollment(p_user_id, p_method, p_secret_encrypted)` | INSERT ON CONFLICT. For TOTP stores encrypted secret; for email_otp secret is NULL. Sets status=pending, clears failed_attempts and locked_until. |
| `activate_2fa(p_user_id)` | Sets status=active, confirmed_at=now(). |
| `replace_backup_codes(p_user_id, p_hashes text[])` | Deletes all existing codes, inserts new set. Single statement. |
| `start_2fa_challenge(p_token_hash, p_kind)` | Validates challenge token (kind + expiry + not-revoked). Returns enrollment data (method, encrypted_secret, last_used_counter, failed_attempts, locked_until). |
| `verify_2fa_success(p_user_id, p_counter)` | Resets failed_attempts, updates last_used_at, last_used_counter. |
| `verify_2fa_failure(p_user_id, p_failed, p_locked_until)` | Sets failed_attempts and optionally locked_until. |
| `consume_backup_code(p_user_id, p_code_hash)` | Sets used_at=now() on matching code. |
| `get_unused_backup_codes(p_user_id)` | Returns all unused code hashes. |
| `issue_email_otp(p_user_id, p_token_hash, p_expires_at)` | Revokes prior two_factor_email_otp tokens, inserts new one. |
| `lookup_email_otp(p_user_id, p_code_hash)` | Finds unrevoked, unexpired email OTP matching hash. |
| `consume_token_and_verify_email(p_token_hash)` | Validates email_verify token, sets email_verified_at=now(), revokes token. **Idempotent:** if already verified, returns user_id without error. |
| `consume_password_reset_token(p_token_hash, p_new_password_hash)` | Validates password_reset token, updates password_hash, revokes token, revokes all refresh tokens. |
| `lookup_user_email(p_user_id)` | Returns (email, full_name). Narrow. |
| `issue_token_for_email(p_user_id, p_kind, p_token_hash, p_expires_at)` | Wrapper around insert_auth_token for email-specific flows. |

**Commit message:**
```
Add SECURITY DEFINER functions for 2FA, email verify and password reset

- lookup_challenge_token: validates enrollment/pending tokens by hash
- upsert_2fa_enrollment, activate_2fa: enrollment lifecycle
- start_2fa_challenge, verify_2fa_success/failure: challenge flow
- backup code management: replace, get_unused, consume
- email OTP: issue, lookup (revokes prior OTPs on re-issue)
- consume_token_and_verify_email: idempotent email verification
- consume_password_reset_token: resets password and revokes sessions
- lookup_user_email: narrow email/full_name read for sending
```

**Verification:** `supabase db push` applies cleanly. `\df app.*` shows all new functions. Each callable by `app_backend`, denied to `PUBLIC`.

---

### Phase 2 — Crypto Utilities, Email Sender & Config

**No routes or endpoints in this phase.** Pure utilities, independently testable.

#### 2a. Config

**File:** `backend/app/core/config.py`

Add to `Settings`:
```python
totp_encryption_key: str = Field(validation_alias="TOTP_ENCRYPTION_KEY")
email_provider: str = Field(default="logging", validation_alias="EMAIL_PROVIDER")
resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")
email_from: str = Field(default="noreply@edubridge.ai", validation_alias="EMAIL_FROM")
app_base_url: str = Field(default="http://localhost:3000", validation_alias="APP_BASE_URL")
two_factor_lockout_thresholds: list[tuple[int, int]] = [
    (3, 300),    # 3 failures → 5 min lock
    (6, 900),    # 6 failures → 15 min lock
    (10, 3600),  # 10 failures → 1 hour lock
]
```

**File:** `backend/.env.example` — add `TOTP_ENCRYPTION_KEY`, `EMAIL_PROVIDER`, `RESEND_API_KEY`, `EMAIL_FROM`, `APP_BASE_URL`.

#### 2b. TOTP utilities

**New file:** `backend/app/auth/totp.py`

```python
def generate_totp_secret() -> str
def build_otpauth_uri(secret: str, email: str) -> str
def generate_qr_svg(otpauth_uri: str) -> str
def verify_totp_code(secret: str, code: str, *, last_counter: int | None = None) -> int | None
def encrypt_secret(plaintext: str) -> bytes
def decrypt_secret(ciphertext: bytes) -> str
```

- `verify_totp_code` checks ±1 window, rejects counter ≤ last_counter (replay guard), returns counter on success or None on failure.
- `generate_qr_svg` uses `qrcode.image.svg.SvgPathImage` — no `<script>` injection surface.

#### 2c. Backup code utilities

**New file:** `backend/app/auth/backup_codes.py`

```python
def generate_backup_codes(count: int = 10) -> list[str]
def hash_backup_code(code: str) -> str    # uppercases before argon2id
def verify_backup_code(code: str, code_hash: str) -> bool  # uppercases before verify
```

Alphabet: `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no 0/O/1/I).

#### 2d. Email sender

**New file:** `backend/app/auth/email.py`

```python
class EmailSender(Protocol):
    def send(self, to: str, subject: str, html_body: str) -> None: ...

class LoggingEmailSender:   # dev: logs to, subject, body_length
class ResendEmailSender:    # prod: sends via Resend API
def get_email_sender() -> EmailSender  # factory from EMAIL_PROVIDER
```

#### 2e. Email templates

**New file:** `backend/app/auth/email_templates.py`

```python
def verification_email(url: str) -> str
def password_reset_email(url: str) -> str
def two_factor_otp_email(code: str, expires_minutes: int) -> str
```

#### 2f. Onboarding-scoped JWT

**File:** `backend/app/auth/security.py`

Modify `create_access_token` to accept `token_type: str = "access"`.  
Modify `decode_access_token` to accept `expected_type: str = "access"`.  
Add `create_onboarding_token(user_id) -> (token, expires_in)` that calls with `token_type="onboarding"`.

The existing `authenticated` dependency calls `decode_access_token(token)` which defaults to `expected_type="access"` — onboarding tokens are automatically rejected everywhere.

**Commit message:**
```
Add TOTP, backup code, email, and onboarding-token utilities

- totp.py: secret generation, otpauth URI, QR SVG, code verification
  with ±1 window and replay guard (pyotp + qrcode)
- backup_codes.py: 8-char alphanumeric generation, argon2id hashing,
  case-insensitive comparison
- email.py: EmailSender protocol, LoggingEmailSender (dev),
  ResendEmailSender (prod), factory from EMAIL_PROVIDER
- email_templates.py: transactional HTML for verify, reset, OTP
- security.py: onboarding-scoped JWT (type:"onboarding" rejected by
  the existing authenticated dependency)
- config.py: TOTP_ENCRYPTION_KEY, EMAIL_PROVIDER, RESend_API_KEY,
  EMAIL_FROM, APP_BASE_URL
```

**Verification:** `pytest tests/unit` passes (new unit tests). `ruff check` + `ruff format --check` pass.

---

### Phase 3 — 2FA Service & Endpoints

#### 3a. Schemas

**File:** `backend/app/auth/schemas.py`

```python
# --- 2FA Enrolment ---
class TwoFactorEnrollRequest(BaseModel):
    method: Literal["totp", "email_otp"]
    enrollment_token: str

class TwoFactorEnrollResponseTOTP(BaseModel):
    method: Literal["totp"]
    secret: str
    otpauth_uri: str
    qr_svg: str

class TwoFactorEnrollResponseEmailOTP(BaseModel):
    method: Literal["email_otp"]
    sent_to: str
    expires_in: int

TwoFactorEnrollResponse = TwoFactorEnrollResponseTOTP | TwoFactorEnrollResponseEmailOTP

class TwoFactorConfirmRequest(BaseModel):
    code: str
    enrollment_token: str

class TwoFactorConfirmResponse(BaseModel):
    two_factor: TwoFactorOut
    backup_codes: list[str]
    onboarding_state: str
    access_token: str
    expires_in: int

# --- 2FA Challenge ---
class TwoFactorVerifyRequest(BaseModel):
    pending_token: str
    code: str
    type: Literal["totp", "email_otp", "backup_code"]

class TwoFactorVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    onboarding_state: str

class TwoFactorResendRequest(BaseModel):
    pending_token: str

class TwoFactorResendResponse(BaseModel):
    sent_to: str
    expires_in: int

# --- Email Verification ---
class EmailVerifyRequest(BaseModel):
    token: str

class EmailVerifyResponse(BaseModel):
    email_verified: bool
    onboarding_state: str
    access_token: str
    expires_in: int
    enrollment_token: str

class EmailResendRequest(BaseModel):
    email: EmailStr

# --- Password Reset ---
class PasswordForgotRequest(BaseModel):
    email: EmailStr

class PasswordResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

# --- Backup Code Regeneration ---
class BackupCodesRegenerateResponse(BaseModel):
    backup_codes: list[str]  # 10 × 8 alphanumeric, shown once
```

#### 3b. Error factories

**File:** `backend/app/core/errors.py`

```python
def two_factor_invalid() -> AppError:
    return AppError(code="TWO_FACTOR_INVALID", message="Invalid or expired code.", status_code=401)

def pending_token_expired() -> AppError:
    return AppError(code="PENDING_TOKEN_EXPIRED", message="Challenge expired. Please sign in again.", status_code=401)

def invalid_token(message: str = "Invalid or unknown token.") -> AppError:
    return AppError(code="INVALID_TOKEN", message=message, status_code=400)

def token_expired(message: str = "This link has expired.") -> AppError:
    return AppError(code="TOKEN_EXPIRED", message=message, status_code=410)

def two_factor_locked(locked_until: str) -> AppError:
    return AppError(
        code="TWO_FACTOR_LOCKED",
        message="Too many failed attempts. Try again later.",
        status_code=423,
        details={"locked_until": locked_until},
    )
```

> **Note:** `two_factor_locked` already exists in `backend/app/core/errors.py` from KAN-10. The plan lists it here so the implementer knows it is the factory to call from `two_factor_verify` step 5 — no new function needs to be written, only reused.

#### 3c. Service functions

**File:** `backend/app/auth/service.py`

**`two_factor_enroll(db, payload)`:**
1. Hash enrollment_token, lookup via `app.lookup_challenge_token(hash, 'two_factor_enrollment')`
2. Assert not revoked, not expired
3. Look up existing enrollment: if `status = 'active'` → `400 VALIDATION_ERROR` ("2FA is already active")
4. If `method = "totp"`: generate secret → encrypt → `app.upsert_2fa_enrollment(user_id, 'totp', encrypted)` → build otpauth URI → generate QR SVG → return
5. If `method = "email_otp"`: `app.upsert_2fa_enrollment(user_id, 'email_otp', NULL)` → generate 6-digit OTP → hash → `app.issue_email_otp(user_id, hash, expires_at)` → lookup email via `app.lookup_user_email(user_id)` → send email → return masked address

**`two_factor_confirm(db, payload)`:**
1. Hash enrollment_token, lookup via `app.lookup_challenge_token(hash, 'two_factor_enrollment')`
2. Assert not revoked, not expired
3. Read enrollment row (method, encrypted secret)
4. If `method = "totp"`: decrypt secret → `verify_totp_code(secret, code)` → None = failure
5. If `method = "email_otp"`: hash code → `app.lookup_email_otp(user_id, hash)` → None = failure
6. On success: `app.activate_2fa(user_id)` → generate 10 backup codes → hash each → `app.replace_backup_codes(user_id, hashes)` → revoke enrollment token → issue refresh token + access token → derive onboarding_state
7. Return response with backup codes and tokens

**`two_factor_verify(db, payload)`:**
1. Hash pending_token, lookup via `app.lookup_challenge_token(hash, 'two_factor_pending')` — **ASSERT kind is `two_factor_pending`**
2. Not found or expired → `PENDING_TOKEN_EXPIRED` (401)
3. Revoked → `PENDING_TOKEN_EXPIRED` (401)
4. `app.start_2fa_challenge(hash, 'two_factor_pending')` → get enrollment data
5. `locked_until > now()` → raise `errors.two_factor_locked(locked_until.isoformat())` — `423 TWO_FACTOR_LOCKED`
6. Based on `type`:
   - `"totp"`: decrypt secret → `verify_totp_code(secret, code, last_counter=counter)`
   - `"email_otp"`: hash code → `app.lookup_email_otp(user_id, hash)`
   - `"backup_code"`: `app.get_unused_backup_codes(user_id)` → iterate with `verify_backup_code(code, hash)` → match: `app.consume_backup_code(user_id, matched_hash)`
7. Success: `app.verify_2fa_success(user_id, counter)` → revoke pending token → issue access + refresh tokens → derive onboarding_state
8. Failure: increment failed_attempts → compute locked_until → `app.verify_2fa_failure(user_id, failed, locked_until)` → audit_log → raise `TWO_FACTOR_INVALID`

**`two_factor_resend(db, payload)`:**
1. Hash pending_token, lookup via `app.lookup_challenge_token(hash, 'two_factor_pending')`
2. Read enrollment: method must be `email_otp` → else `422 VALIDATION_ERROR`
3. Generate new OTP → hash → `app.issue_email_otp(user_id, hash, expires_at)` (revokes prior)
4. Lookup email → send → return masked address

**`verify_email(db, payload)`:**
1. Hash token, lookup via `app.lookup_challenge_token(hash, 'email_verify')`
2. Expired → `TOKEN_EXPIRED` (410)
3. Not found: call `app.consume_token_and_verify_email(hash)` which is idempotent — if already verified, returns user_id; if never valid → `INVALID_TOKEN` (400)
4. Found and valid: `app.consume_token_and_verify_email(hash)` → issue enrollment_token → issue onboarding-scoped access_token → derive onboarding_state

**`resend_email_verification(db, payload)`:**
1. Lookup user via `app.lookup_user_for_login(email)` (reuses existing SECURITY DEFINER)
2. Found or not: run `verify_password("x", _dummy_password_hash())` + dummy timing
3. If found and email not yet verified: issue new `email_verify` token → send verification email
4. Return nothing (void)

**`forgot_password(db, payload)`:**
1. Lookup user via `app.lookup_user_for_login(email)`
2. Found or not: run `verify_password("x", _dummy_password_hash())` + dummy timing
3. If found and `email_verified_at IS NOT NULL`: issue `password_reset` token → send reset email
4. Return nothing (void)

**`reset_password(db, payload)`:**
1. Hash token, lookup via `app.lookup_challenge_token(hash, 'password_reset')`
2. Expired → `TOKEN_EXPIRED` (410). Not found → `INVALID_TOKEN` (400)
3. Hash new password → `app.consume_password_reset_token(hash, new_hash)` (updates password, revokes token, revokes all refresh tokens)
4. Return nothing

**`two_factor_regenerate_backup_codes(db, user_id)`:**
1. Read `two_factor_enrollment` for user_id — if no row or `status != 'active'` → `403 FORBIDDEN_SCOPE` ("2FA is not active; enrol first")
2. Generate 10 new backup codes via `generate_backup_codes()`
3. Hash each via `hash_backup_code()`
4. Call `app.replace_backup_codes(user_id, hashes)` — deletes old set, inserts new set in one statement
5. Write audit_log entry: `action = 'backup_codes_regenerated'`
6. Return `{"backup_codes": plaintext_codes}` — shown once, never stored in plaintext

#### 3d. Route wiring

**File:** `backend/app/auth/routes.py`

| Method | Path | Rate Limit |
|---|---|---|
| `POST` | `/auth/2fa/enroll` | 3/5min |
| `POST` | `/auth/2fa/confirm` | 5/5min |
| `POST` | `/auth/2fa/verify` | 10/5min |
| `POST` | `/auth/2fa/resend` | 5/5min |
| `POST` | `/auth/email/verify` | 10/5min |
| `POST` | `/auth/email/resend` | 3/5min |
| `POST` | `/auth/password/forgot` | 3/5min |
| `POST` | `/auth/password/reset` | 5/5min |
| `POST` | `/auth/2fa/backup-codes` | 3/5min |

New rate-limit constants in `backend/app/core/ratelimit.py`:
```python
TWO_FA_ENROLL_LIMIT = Limit(max_requests=3, window_seconds=300)
TWO_FA_CONFIRM_LIMIT = Limit(max_requests=5, window_seconds=300)
TWO_FA_VERIFY_LIMIT = Limit(max_requests=10, window_seconds=300)
TWO_FA_RESEND_LIMIT = Limit(max_requests=5, window_seconds=300)
EMAIL_VERIFY_LIMIT = Limit(max_requests=10, window_seconds=300)
EMAIL_RESEND_LIMIT = Limit(max_requests=3, window_seconds=300)
PASSWORD_FORGOT_LIMIT = Limit(max_requests=3, window_seconds=300)
PASSWORD_RESET_LIMIT = Limit(max_requests=5, window_seconds=300)
BACKUP_CODES_REGENERATE_LIMIT = Limit(max_requests=3, window_seconds=300)
```

**Commit message:**
```
Implement 2FA enrolment, challenge, email verification, and password reset

- 2FA enroll: TOTP (secret + QR SVG) or email OTP, enrollment_token in body
- 2FA confirm: verify first code, activate, issue 10 backup codes once,
  return access_token so enrolment does not force a second login
- 2FA verify: pending_token in body, ASSERT kind is two_factor_pending
  (rejects enrollment tokens), TOTP/email_otp/backup_code verification,
  server-side lockout, replay guard via last_used_counter
- 2FA resend: pending_token, email_otp only (TOTP uses backup code)
- 2FA backup-codes: authenticated regeneration, invalidates old set (tdd §3.1)
- email/verify: idempotent — spent token returns success if already verified,
  issues onboarding-scoped access token (type:"onboarding", rejected by
  authenticated dependency on every business endpoint)
- email/resend: constant-time whether or not address exists
- password/forgot: identical response body, status AND TIMING for known
  and unknown addresses (dummy hash + dummy send)
- password/reset: consumes token, updates password, revokes all refresh tokens
```

**Verification:** `pytest tests/unit` passes. `pytest tests/integration -k "twofa or email_verify or password"` passes.

---

### Phase 4 — Tests

#### 4a. Unit tests (no database)

**New file:** `backend/tests/unit/test_totp.py`
- `test_generate_totp_secret_is_base32` — 32 chars, valid base32
- `test_build_otpauth_uri_format` — starts with `otpauth://totp/`, contains secret + issuer
- `test_generate_qr_svg_is_valid_svg` — starts with `<svg`, no `<script>`
- `test_encrypt_decrypt_roundtrip` — Fernet roundtrip
- `test_decrypt_tampered_ciphertext_fails` — modified ciphertext raises
- `test_verify_totp_valid_code` — correct code returns counter
- `test_verify_totp_wrong_code` — wrong code returns None
- `test_verify_totp_replay_guard` — code at counter ≤ last_counter rejected

**New file:** `backend/tests/unit/test_backup_codes.py`
- `test_generate_10_unique_codes` — 10 codes, all different, 8 chars
- `test_codes_use_unambiguous_alphabet` — no 0, O, 1, I
- `test_hash_is_argon2id` — starts with `$argon2id$`
- `test_verify_case_insensitive` — mixed case matches
- `test_verify_wrong_code_false`

**New file:** `backend/tests/unit/test_onboarding_token.py`
- `test_onboarding_token_roundtrip` — create type=onboarding, decode with expected_type=onboarding
- `test_onboarding_token_rejected_by_default_decode` — default decode raises
- `test_access_token_rejected_by_onboarding_decode` — access token with expected_type=onboarding raises

#### 4b. Integration tests (database, rolled-back transaction)

**New file:** `backend/tests/integration/test_2fa_enrollment.py` (10 tests)
- `test_enroll_totp_returns_secret_and_qr`
- `test_enroll_email_otp_returns_sent_to`
- `test_enroll_rejects_pending_token` — pending_token at /2fa/enroll → 401
- `test_enroll_rejects_expired_token`
- `test_enroll_rejects_when_already_active`
- `test_confirm_totp_activates_and_returns_backup_codes`
- `test_confirm_email_otp_activates`
- `test_confirm_wrong_code_401`
- `test_confirm_returns_access_token_usable_for_me`
- `test_backup_codes_shown_exactly_once` — re-enrolment generates different codes

**New file:** `backend/tests/integration/test_2fa_challenge.py` (13 tests)
- `test_verify_totp_returns_session`
- `test_verify_email_otp_returns_session`
- `test_verify_backup_code_returns_session`
- `test_verify_rejects_enrollment_token` — **THE critical security test**
- `test_verify_wrong_code_401`
- `test_verify_locked_after_3_failures`
- `test_lockout_survives_page_reload` — locked_until in DB
- `test_totp_replay_rejected` — same code twice within window
- `test_backup_code_single_use` — works once, second → 401
- `test_backup_code_case_insensitive`
- `test_resend_email_otp_succeeds`
- `test_resend_rejects_totp_user`
- `test_pending_token_expired`

**New file:** `backend/tests/integration/test_2fa_backup_codes.py` (4 tests)
- `test_regenerate_backup_codes_returns_10_new_codes`
- `test_regenerate_backup_codes_invalidates_old_set` — codes from enrolment no longer work after regeneration
- `test_regenerate_requires_active_2fa` — no enrollment row or status != active → 403
- `test_regenerate_requires_authentication` — no bearer token → 401

**New file:** `backend/tests/integration/test_email_password.py` (11 tests)
- `test_email_verify_succeeds`
- `test_email_verify_idempotent` — second call with spent token → 200
- `test_email_verify_expired_token`
- `test_email_verify_invalid_token`
- `test_onboarding_token_cannot_call_me` — **THE scoping test**
- `test_email_resend_constant_time` — same response for known/unknown
- `test_password_forgot_constant_time` — same response body for known/unknown
- `test_password_reset_succeeds` — login with new password works
- `test_password_reset_revokes_refresh_tokens`
- `test_password_reset_expired_token`
- `test_password_reset_invalid_token`

**New file:** `backend/tests/integration/test_2fa_rls.py` (3 tests)
- `test_two_factor_enrollment_invisible_without_bound_user`
- `test_two_factor_backup_codes_invisible_without_bound_user`
- `test_two_factor_enrollment_owner_only`

**Commit message:**
```
Add unit and integration tests for 2FA, email verify, password reset

Unit (no DB): TOTP generation/verification/replay, backup codes
case-insensitive, onboarding token scoping

Integration (rolled-back transaction):
- 2FA enrolment: TOTP/email_otp, kind assertion, confirm, backup codes once
- 2FA challenge: verify all types, enrollment token REJECTED at /2fa/verify,
  lockout persists, TOTP replay guard, backup single-use + case-insensitive
- Email/password: idempotent verify, onboarding token cannot call /me,
  constant-time resend/forgot, reset revokes refresh tokens
- RLS: two_factor tables invisible without bound user, owner-only
```

**Verification:** `pytest tests/unit` passes without `DATABASE_URL`. `pytest tests/integration` passes against Supabase. CI green.

---

## Stress Test — Pass 1

| # | Attack / Failure | Defence |
|---|---|---|
| 1 | Missing `set_current_user_id` on any path | All endpoints pre-auth; use SECURITY DEFINER exclusively; no `get_service_db()` |
| 2 | Mid-request `commit()` discards RLS context | No mid-request commits in any new function |
| 3 | Enrollment token accepted at `/2fa/verify` | `lookup_challenge_token(hash, 'two_factor_pending')` asserts kind. Tested. |
| 4 | Email-verify access token reaching `/auth/me` | JWT `type:"onboarding"` rejected by `decode_access_token()` default. Tested. |
| 5 | Backup codes compared case-sensitively | Both sides uppercased before hash/verify. Tested. |
| 6 | TOTP code replayable within window | `last_used_counter` in DB, checked before accepting. Tested. |
| 7 | Timing reveals whether address exists | `forgot_password` and `resend_email_verification` run dummy hash + dummy send on not-found path |
| 8 | Lockout reset by page reload | `locked_until` persisted in DB. Tested. |
| 9 | Secrets in logs or responses | Fernet-encrypted at rest; `LoggingEmailSender` logs body_length not body; QR has no `<script>` |
| 10 | Re-enrolment while already active | Explicit `status = 'active'` check before upsert |
| 11 | Wrong token kind at `/2fa/confirm` | Kind assertion in `lookup_challenge_token` |
| 12 | Cross-user password reset | Token is hash-looked-up, user_id comes from the token row |
| 13 | Email OTP brute-force | Rate limit (10/5min) + lockout after 3 failures + single-use OTPs |
| 14 | `/2fa/enroll` re-call abuse | Rate limited (3/5min); upsert overwrites in single row |

## Stress Test — Pass 2

All 14 items from Pass 1 re-reviewed. No unresolved issues. Key confirmations:
- `LoggingEmailSender` logs body_length, not body content — token not exposed
- `upsert_2fa_enrollment` is `INSERT ON CONFLICT DO UPDATE` — no orphaned secrets
- `lookup_challenge_token` takes `p_kind token_kind` — PostgreSQL enum enforces at SQL level

---

## Definition of Done

- [ ] A user enrols in TOTP or email OTP and receives 10 backup codes ONCE
- [ ] `/2fa/verify` exchanges a pending token for a real session
- [ ] `/2fa/verify` REJECTS an enrolment token (assert the kind)
- [ ] A backup code works once, case-insensitively, and never again
- [ ] `POST /auth/2fa/backup-codes` regenerates codes and invalidates the old set (authenticated, active 2FA required)
- [ ] Repeated failures lock temporarily with a server-side `locked_until`
- [ ] `email/verify` issues an onboarding-scoped token that CANNOT call `/api/auth/me`
- [ ] `password/forgot` answers identically for known and unknown addresses (body, status AND TIMING)
- [ ] With `app.current_user_id` unset, queries return ZERO rows
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `pytest tests/unit` passes without `DATABASE_URL`
- [ ] `pytest tests/integration` passes against Supabase
- [ ] CI pipeline (`backend.yml`) green on PR

---

## Files Modified/Created

| File | Action |
|---|---|
| `supabase/migrations/20260803120000_2fa_email_password_lookups.sql` | **New** |
| `backend/app/core/config.py` | **Edit** — add 6 config fields |
| `backend/.env.example` | **Edit** — add 5 env vars |
| `backend/app/auth/security.py` | **Edit** — onboarding token type param |
| `backend/app/auth/totp.py` | **New** |
| `backend/app/auth/backup_codes.py` | **New** |
| `backend/app/auth/email.py` | **New** |
| `backend/app/auth/email_templates.py` | **New** |
| `backend/app/auth/schemas.py` | **Edit** — add schemas for all 9 endpoints (see §3a) |
| `backend/app/auth/service.py` | **Edit** — add 9 service functions |
| `backend/app/auth/routes.py` | **Edit** — add 9 endpoints |
| `backend/app/core/errors.py` | **Edit** — add 4 new error factories, reuse existing `two_factor_locked` from KAN-10 |
| `backend/app/core/ratelimit.py` | **Edit** — add 9 limit constants |
| `backend/pyproject.toml` | **Edit** — add 4 dependencies |
| `backend/uv.lock` | **Regenerated** via `uv lock` |
| `backend/requirements.txt` | **Regenerated** via `uv export` |
| `backend/requirements-dev.txt` | **Regenerated** via `uv export` |
| `backend/tests/unit/test_totp.py` | **New** |
| `backend/tests/unit/test_backup_codes.py` | **New** |
| `backend/tests/unit/test_onboarding_token.py` | **New** |
| `backend/tests/integration/test_2fa_enrollment.py` | **New** |
| `backend/tests/integration/test_2fa_challenge.py` | **New** |
| `backend/tests/integration/test_2fa_backup_codes.py` | **New** |
| `backend/tests/integration/test_email_password.py` | **New** |
| `backend/tests/integration/test_2fa_rls.py` | **New** |

---

## Assumptions

1. `pyotp`, `cryptography`, `qrcode`, and `resend` are available on PyPI and compatible with Python 3.12+
2. `TOTP_ENCRYPTION_KEY` is generated once and shared across all app instances in a deployment
3. The `app_backend` role has INSERT/UPDATE/DELETE grants on `two_factor_enrollment` and `two_factor_backup_code` (from `rls_policies.sql` blanket GRANT)
4. `audit_log` INSERT policy is `WITH CHECK (true)` — audit writes work without a bound user
5. Frontend contract types in `frontend/lib/api/types.ts` are authoritative — backend must match field-for-field

---

## Open Questions

1. **`GET /subscription` and `POST /subscription/select`** — unowned. The onboarding derivation depends on subscription status. This is not blocking this card but should be assigned.
2. **Guardian invite email template** — stubbed in `email_templates.py`. Mujtaba's card should complete it.
3. **Admin-assisted 2FA reset** (`POST /api/admin/users/{id}/2fa/reset`) — specified in `tdd.md` §6.9 but out of scope (admin module not built).
