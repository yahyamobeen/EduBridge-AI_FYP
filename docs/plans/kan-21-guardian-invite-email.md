# KAN-21 — Guardian Invite Email Delivery

**Branch:** `KAN-21-guardian-workflow`
**Date:** August 16, 2026
**Status:** **IMPLEMENTED** — `service.guardian_invite` now builds and queues the guardian invite email
(commit not yet made; repository owner runs git).
**Source of truth:** `prd.md` · `tdd.md` · applied SQL in `supabase/migrations/` · existing code
**Depends on:** KAN-10 (auth core — register, login, refresh, logout, me) · KAN-10b (email seam)

---

## What the ticket is

For Classes 9 & 10 the guardian link is **mandatory** before the dashboard unlocks. The student,
after email verification, must land on the guardian page, enter the parent's email, and the parent
receives a **verification-email button** to confirm and link. One guardian may have more than one
student and sees each one's progress separately.

**This card's scope is the missing email delivery** so the guardian actually receives the invite.
The gate, link creation, token issuance, and confirm flow are already implemented; the email send is not.

---

## Diagnosis (why the guardian isn't getting the email)

Traced the actual flow (not assumed):

1. Frontend `GuardianGate.tsx` calls `POST /auth/guardian/invite` (`endpoints.ts:151`).
2. `routes.py:303` `guardian_invite_endpoint` → `service.guardian_invite`.
3. `service.guardian_invite` (service.py:1210):
   - validates parent exists (`app.lookup_parent_id_by_email`), rejects self-link,
   - upserts the `guardian_link` row to `pending`,
   - calls `revoke_user_tokens` + `issue_guardian_invite_token` and **captures the returned plain token**,
   - returns `{"invite_sent": True, ...}`.
4. **It never sends an email.** The plain token is discarded. `send_async` is imported
   (`service.py:14`) but never called for the invite. There is no call to
   `guardian_invite_email`/`build_guardian_invite_url`.

Evidence this is the missing half:
- `email_templates.py:124-125`: "Wired by `service.guardian_invite` once both branches are merged;
  the delivery seam is the missing half of that flow."
- `email.py` has a fully working `send_async` seam (used by the other flows).

So the response lies (`invite_sent: True`) while no email is produced. That is the defect.

---

## Scope

| Area | Endpoint | Work |
|---|---|---|
| **A. Deliver the invite email** | `POST /auth/guardian/invite` | Wire the email send into `service.guardian_invite` |

**Out of scope:** guardian confirm/gate logic (already built) · one-guardian-many-students parent
dashboard (Yahya/frontend) · the self-link / parent-lookup behaviour · changing the token format.

---

## Implementation plan

### 1. `service.guardian_invite` — send the email
After `issue_guardian_invite_token(db, student_id)` returns `plain_token`, build and queue:

```python
url = build_guardian_invite_url(plain_token, locale)
subject, body = guardian_invite_email(url=url, student_name=student_name)
_queue_email(parent_email, subject, body)
```

Notes:
- `parent_email` (lowercased) is already available; use the real address, not the masked one
  returned to the client.
- Locale: pass through `payload` if present, else default (`email_templates` already defaults).
- `student_name` should come from the student row (it is not fetched today — add it to the
  existing `SELECT email FROM app_user` so we do not add a second query).
- Use the existing `_queue_email` (= `email.send_async`) seam; do NOT send synchronously.
- Keep `invite_sent: True` — it is now truthful.

### 2. Tests
- **Unit** (backend): assert `guardian_invite` calls `send_async` with the guardian's real email,
  subject containing the student name, and a body containing the confirm URL with the issued token.
  Use the existing `EMAIL_PROVIDER=logging` + `drain_pending_emails` pattern from `test_email_locale.py`.
- Add to `test_email_locale.py` list any new locale-sensitive builder if required (none expected).

### 3. Docs / changelog
- Append a line to the architecture doc for auth (where the other email flows are documented) and
  to the running changelog — per the repo update mandate (no `Claude/HISTORY.md` exists at the
  `EduBridge-AI_FYP` root; confirm the actual changelog path with the team lead before editing).

---

## Verification

| Check | Command |
|---|---|
| Backend lint/format/unit | `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit -q` |
| Integration (live DB) | `uv run pytest tests/integration -q` (needs `DATABASE_URL`, `SERVICE_ROLE_DATABASE_URL`) |
| Manual | `EMAIL_PROVIDER=logging`, run invite, confirm the guardian email with the confirm link is logged |

---

## Open questions for the team lead
- Where is the running changelog for `EduBridge-AI_FYP` (the `Claude/HISTORY.md` path referenced in
  the top-level `CLAUDE.md` does not exist here)?
- Should the email body include the student's name, and is there a locale field on
  `GuardianInviteRequest` (or should we always use the default)?

---

## Implementation record (August 16, 2026)

**Changed files:**
- `backend/app/auth/service.py` — `guardian_invite`:
  - Extended the student lookup to also fetch `full_name` and `language_pref` (LEFT JOIN
    `student_profile`; `full_name` is on `app_user`, `language_pref` on `student_profile`).
  - Captured the token returned by `issue_guardian_invite_token` (it was previously discarded).
  - Built the confirm URL via `build_guardian_invite_url(plain_token, locale)` (locale from
    `web_locale(student["language_pref"])`, English fallback), rendered
    `guardian_invite_email(url, student_name, locale)` (name falls back to "Student"), and
    queued delivery via the existing `_queue_email` seam.
- `backend/tests/integration/test_guardian_flow.py` — added
  `TestInvite::test_invite_queues_an_email_to_the_parent`, which patches `service._queue_email`
  to capture the message and asserts it goes to the parent's real address with the student's
  name in the subject and the `/en/guardian/confirm?token=` URL in the body.

**Verification (real output):**
- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 55 files already formatted
- `uv run pytest tests/unit -q` → **147 passed**
- `uv run pytest tests/integration/test_guardian_flow.py -q` (live DB) → **27 passed**

**Doc mandate:** no architecture doc or `Claude/HISTORY.md` exists in `EduBridge-AI_FYP`; this
plan file is the record of the change. Confirm the real changelog path with the team lead.

**Deployment note (delivery):** code now sends the email, but **no real email is delivered** until
`backend/.env` is on a real provider and out of sandbox. Current `.env` has
`EMAIL_PROVIDER=logging` — for tomorrow's demo, flip to `EMAIL_PROVIDER=resend` and whitelist the
demo address(es) in the Resend dashboard (Resend sandbox only mails whitelisted recipients from
`onboarding@resend.dev`).