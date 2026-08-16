# Change Log — KAN-21 (Guardian Invite Email) + SendGrid Swap

> Purpose: track every change made on `KAN-21-guardian-workflow` since it was
> pulled from the latest upstream, so the later merge to `main` is conflict-free.

## Branch context
- **Base commit:** `eea0e74` (Merge pull request #16 from yahyamobeen/fixed-deployment)
- **Working branch:** `KAN-21-guardian-workflow`
- **Merge target:** `main`

## Provider decision
- **Transactional email provider resolved to SendGrid (free tier)** — replaces the
  default `logging` and the Resend sandbox. SendGrid delivers to **any** inbox
  (Resend's sandbox only reached the account owner), which is required for the
  guardian invite to reach a real parent. Verification, 2FA codes, password resets
  and the guardian invite all flow through the same `EmailSender` seam, so no auth
  logic changed. `.env` (local, not committed) now sets `EMAIL_PROVIDER=sendgrid`,
  `SENDGRID_API_KEY`, and `EMAIL_FROM=<verified sender>`.

## Files changed (6) + files added (1) + docs (2)

### 8. `docs/plans/change-log-kan-21.md` — this file
**Changes:** documents all changes made on this branch since `eea0e74`.

### 9. Documentation — `prd.md` + `tdd.md`
**Changes:**
- `prd.md`: added changelog row **0.3.6** (SendGrid provider) + a line in §6.2
  noting transactional mail is delivered via SendGrid.
- `tdd.md`: added changelog row **0.3.8** (SendGrid), corrected the stale 0.3.6
  claim ("No provider is chosen" → later resolved to SendGrid), and added
  `EMAIL_PROVIDER` / `SENDGRID_API_KEY` / `EMAIL_FROM` rows to §8.2.

### 1. `backend/app/auth/service.py` — KAN-21 guardian invite email (the core fix)
**Problem found:** `guardian_invite()` created the link + token but returned
`invite_sent: True` without ever sending the email. The parent never received
the invite.

**Changes:**
- Student lookup now `LEFT JOIN student_profile` to fetch `full_name` +
  `language_pref` (previously `SELECT email` only).
- After `issue_guardian_invite_token`, now:
  - builds the confirm URL: `build_guardian_invite_url(plain_token, locale)`
  - renders the email: `guardian_invite_email(url, student_name, locale)`
    (name falls back to `"Student"`)
  - queues delivery: `_queue_email(parent_email, subject, html)`
- Imports added: `build_guardian_invite_url`, `guardian_invite_email`.

### 2. `backend/app/auth/email.py` — SendGrid provider (new)
**Changes:**
- Added `SendGridEmailSender` implementing the `EmailSender` protocol
  (`send(to, subject, html_body)`), using the SendGrid Web API.
- `get_email_sender()` returns `SendGridEmailSender` when
  `EMAIL_PROVIDER=sendgrid`.
- `ResendEmailSender` left in place (dormant) pending the decision to remove it.
- Module docstring updated to list the third implementation.

### 3. `backend/app/core/config.py` — SendGrid config
**Changes:**
- Added field `sendgrid_api_key` (alias `SENDGRID_API_KEY`).
- Added validator: `EMAIL_PROVIDER=sendgrid requires EMAIL_FROM`.

### 4. `backend/pyproject.toml` — dependency
**Changes:**
- `email` extra: `["resend>=2.0.0"]` → `["resend>=2.0.0", "sendgrid>=6.11.0"]`.

### 5. `backend/uv.lock` — lockfile
**Changes:**
- Reflects the new `sendgrid` dependency. **Must be committed** or the
  dependency will not install.

### 6. `backend/tests/integration/test_guardian_flow.py` — new test
**Changes:**
- Added `test_invite_queues_an_email_to_the_parent`: patches `_queue_email`,
  asserts the parent's address, student name in the subject, and
  `/en/guardian/confirm?token=` in the body.

### 7. NEW file (not tracked): `docs/plans/kan-21-guardian-invite-email.md`
- The detailed KAN-21 implementation plan + implementation record.

## Files to EXCLUDE from the merge
- `.vs/` — local Visual Studio junk. Do not commit.

## Files to include in the merge
- All changed backend files + the two plan docs + the two source docs:
  `prd.md`, `tdd.md`, `docs/plans/change-log-kan-21.md`,
  `docs/plans/kan-21-guardian-invite-email.md`.
- **Do NOT commit `.env`** — it holds the real `SENDGRID_API_KEY` and
  `EMAIL_FROM`; it is gitignored.

## Verification results (real output, not predicted)
- `ruff check .` — passed
- `ruff format --check .` — 55 files formatted
- `pytest tests/unit -q` — **147 passed**
- `pytest tests/integration/test_guardian_flow.py -q` (live DB) — **27 passed**
- Real SendGrid send — **HTTP 202 Accepted**
- SendGrid Activity API — `status: "delivered"` to `yahyamobeen6@gmail.com`
  (landed in the spam folder — expected for a new unauthenticated free-tier
  sender; delivery itself is confirmed working)

## Conflict-avoidance notes
- `service.py` is the only file touching shared auth logic; the change is
  localized to the `guardian_invite()` function.
- `email.py`, `config.py`, `pyproject.toml`, `uv.lock` are additive (new lines,
  no renames) — low conflict risk.
- `test_guardian_flow.py` adds one test method to an existing class — no
  structural change.