# Implementation Plan: Confirm Password Field for Signup Forms

## Overview
Add a confirm-password field to account creation flows (`StudentSignupForm` and `SimpleSignupForm`) as a client-side UX guard. Mirrors the exact pattern established in `ResetPassword.tsx`. No backend changes — `POST /api/auth/register` accepts only `password`.

---

## Phase 1: i18n Keys (3 locale files)

**Files:** `frontend/messages/en.json`, `frontend/messages/ur.json`, `frontend/messages/ur-Latn.json`

**Namespace:** `signup.common` (already shared by both forms for `fullName`, `email`, `password`, `passwordHint`, etc.)

**New keys to add under `signup.common`:**
```json
{
  "confirmPassword": "Confirm Password",
  "confirmPasswordHint": "Must match the password above.",
  "mismatch": "Both passwords must match."
}
```

**Urdu (ur.json) translations:**
```json
{
  "confirmPassword": "پاس ورڈ کی تصدیق",
  "confirmPasswordHint": "اوپر والے پاس ورڈ سے میل کھانا چاہیے۔",
  "mismatch": "دونوں پاس ورڈ ایک جیسے ہونے چاہئیں۔"
}
```

**Roman-Urdu (ur-Latn.json) translations:**
```json
{
  "confirmPassword": "Password ki tasdeeq",
  "confirmPasswordHint": "Upar wale password se match karna chahiye.",
  "mismatch": "Dono passwords aik jaise hone chahiyen."
}
```

**Commit:** `i18n: add confirm-password label, hint, and mismatch error to signup.common`

---

## Phase 2: StudentSignupForm.tsx — Step 1 (Basic Info)

**File:** `frontend/components/signup/StudentSignupForm.tsx`

**Changes:**

1. **Draft type** — add local-only `confirm_password` (NOT in `Draft` sent to API):
```ts
type Draft = {
  full_name: string
  email: string
  password: string
  confirm_password: string   // UI-local only
  board: string
  class_level: string
  student_group: string
  medium: string
  language_pref: string
}
```

2. **Initial state** — add `confirm_password: ''` to `useState<Draft>` init.

3. **State & derived values:**
```ts
const mismatch = draft.confirm_password !== '' && draft.confirm_password !== draft.password
const basicComplete =
  draft.full_name.trim() !== '' &&
  draft.email.trim() !== '' &&
  draft.password.length >= 8 &&
  draft.confirm_password === draft.password &&
  draft.confirm_password !== ''
```

4. **Step 1 JSX** — add `TextField` after password field:
```tsx
<TextField
  label={tc('confirmPassword')}
  name="confirm_password"
  type="password"
  autoComplete="new-password"
  hint={tc('confirmPasswordHint')}
  required
  error={mismatch ? tc('mismatch') : fieldErrors.confirm_password}
  register={{
    value: draft.confirm_password,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      set('confirm_password', e.target.value),
  }}
/>
```

5. **Submit payload** — verify `registerAccount()` call body does NOT include `confirm_password` (it currently doesn't; just confirm unchanged).

**Commit:** `feat(signup): add confirm-password field to StudentSignupForm step 1`

---

## Phase 3: SimpleSignupForm.tsx — Teacher/Parent Single Step

**File:** `frontend/components/signup/SimpleSignupForm.tsx`

**Changes:**

1. **State:** add `const [confirmPassword, setConfirmPassword] = useState('')`

2. **Derived:**
```ts
const mismatch = confirmPassword !== '' && confirmPassword !== password
const complete =
  fullName.trim() !== '' &&
  email.trim() !== '' &&
  password.length >= 8 &&
  confirmPassword === password &&
  confirmPassword !== ''
```

3. **JSX** — add `TextField` after password field:
```tsx
<TextField
  label={tc('confirmPassword')}
  name="confirm_password"
  type="password"
  autoComplete="new-password"
  hint={tc('confirmPasswordHint')}
  required
  error={mismatch ? tc('mismatch') : fieldErrors.confirm_password}
  register={{
    value: confirmPassword,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setConfirmPassword(e.target.value),
  }}
/>
```

4. **Submit payload** — `registerAccount({ email, password, full_name: fullName, role })` unchanged (no `confirm_password`).

**Commit:** `feat(signup): add confirm-password field to SimpleSignupForm (teacher/parent)`

---

## Phase 4: Tests

### 4a. StudentSignupForm.test.tsx
Extend `completeBasicStep` helper or add new test in `describe('step gating')`:
```ts
it('will not advance until passwords match', async () => {
  const user = userEvent.setup()
  renderForm()

  await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
  await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
  await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
  expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

  await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password124')
  expect(screen.getByText(en.signup.common.mismatch)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeDisabled()

  await user.clear(screen.getByLabelText(en.signup.common.confirmPassword))
  await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
  expect(screen.getByRole('button', { name: en.signup.common.continue })).toBeEnabled()
})
```

### 4b. SimpleSignupForm.test.tsx (NEW FILE)
Create new test file mirroring `StudentSignupForm.test.tsx` conventions:
```ts
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { SimpleSignupForm } from './SimpleSignupForm'

const push = vi.fn()
const registerAccount = vi.fn()

vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/api/endpoints', () => ({ register: (...a: unknown[]) => registerAccount(...a) }))

function renderForm(role: 'teacher' | 'parent' = 'teacher') {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SimpleSignupForm role={role} />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  push.mockReset()
  registerAccount.mockReset()
  registerAccount.mockResolvedValue({ onboarding_state: 'email_verification_pending' })
})

describe('confirm password', () => {
  it('will not submit until passwords match', async () => {
    const user = userEvent.setup()
    renderForm('teacher')

    const submit = screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })
    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'Password123')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password124')
    expect(screen.getByText(en.signup.common.mismatch)).toBeInTheDocument()
    expect(submit).toBeDisabled()

    await user.clear(screen.getByLabelText(en.signup.common.confirmPassword))
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'Password123')
    expect(submit).toBeEnabled()
  })

  it('gates only on length and match, leaving real policy to server', async () => {
    const user = userEvent.setup()
    renderForm('parent')

    await user.type(screen.getByLabelText(en.signup.common.fullName), 'Aisha Khan')
    await user.type(screen.getByLabelText(en.signup.common.email), 'aisha@example.com')
    await user.type(screen.getByLabelText(en.signup.common.password), 'alllowercase')
    await user.type(screen.getByLabelText(en.signup.common.confirmPassword), 'alllowercase')

    expect(screen.getByRole('button', { name: new RegExp(en.signup.common.submit, 'i') })).toBeEnabled()
  })
})
```

**Commit:** `test: add confirm-password mismatch tests for StudentSignupForm and SimpleSignupForm`

---

## Phase 5: Verification & Typecheck

Run locally:
```bash
cd frontend
npm run typecheck
npm test
```

Both must pass. No warnings about missing i18n keys (all three locales updated in Phase 1).

**Commit:** `chore: verify typecheck and tests pass`

---

## Isolation Verification (Pre-commit Checklist)

| Check | Result |
|-------|--------|
| `fields.tsx` only imported by `StudentSignupForm.tsx`, `SimpleSignupForm.tsx`, and their tests | ✅ Verified |
| `StudentSignupForm` only rendered from `/signup/student` | ✅ Verified |
| `SimpleSignupForm` only rendered from `/signup/teacher` and `/signup/parent` | ✅ Verified |
| `registerAccount()` payload in both forms excludes `confirm_password` | ✅ Verified (payload unchanged) |
| New i18n keys only added under `signup.common` — no collisions | ✅ Verified (keys: `confirmPassword`, `confirmPasswordHint`, `mismatch` are new) |
| `TextField` error prop already supports live mismatch (used by `fieldErrors.*` and `hint`/`error` pattern) | ✅ Verified — `TextField` passes `error` to `aria-invalid` and `ErrorText` via `aria-describedby` |
| No backend file touched (`backend/app/auth/schemas.py` only has `password`) | ✅ Verified |

---

## Open Questions (Resolved)

1. **Which forms?** — Both `StudentSignupForm` (step 1) and `SimpleSignupForm` (teacher/parent). Matches scope in task.
2. **New test file for SimpleSignupForm?** — Yes, created as part of Phase 4b. It's a new file but mirrors existing conventions exactly.
3. **Password strength rules?** — NOT added. Only length ≥ 8 is enforced (mirroring `ResetPassword`'s only gated rule). Advisory rules (uppercase, number) are not added to signup — consistent with `ResetPassword`'s comment that "no source states the real password policy."

---

## Definition of Done

- [ ] User typing different value in "Confirm Password" sees inline error before submitting (live, not on-submit)
- [ ] Continue (student, step 1) / Submit (teacher/parent) stays disabled until `password === confirm_password && both non-empty`
- [ ] No `confirm_password` field ever sent to `POST /api/auth/register`
- [ ] All three locale files (en, ur, ur-Latn) carry new keys in sync
- [ ] New/extended tests pass (`npm test`)
- [ ] Typecheck passes (`npm run typecheck`)
- [ ] No regression in existing signup tests

---

## Files Modified

| File | Phase |
|------|-------|
| `frontend/messages/en.json` | 1 |
| `frontend/messages/ur.json` | 1 |
| `frontend/messages/ur-Latn.json` | 1 |
| `frontend/components/signup/StudentSignupForm.tsx` | 2 |
| `frontend/components/signup/SimpleSignupForm.tsx` | 3 |
| `frontend/components/signup/StudentSignupForm.test.tsx` | 4a |
| `frontend/components/signup/SimpleSignupForm.test.tsx` (NEW) | 4b |