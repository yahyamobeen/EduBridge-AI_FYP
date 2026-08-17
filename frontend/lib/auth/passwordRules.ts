/**
 * The password requirements, in one place.
 *
 * They were inline in `ResetPassword.tsx`, duplicated as a bare length check in
 * two signup forms, and the settings screen needs them a fourth time — so the
 * constant moves here and the strings move with it, into `auth.password`. A
 * shared rule whose copy lives under `auth.resetPassword` is a rule the next
 * screen quietly reimplements.
 *
 * ADVISORY, NOT ENFORCED — except the length rules. No source states the real
 * password policy (plan assumption A6), so the client cannot be the authority:
 * enforcing rules stricter than the server's would block valid passwords, and
 * the server's `VALIDATION_ERROR` governs either way. They are shown live
 * because a checklist that fills in as you type is genuinely useful; they are
 * not a gate because the client does not know the rule.
 *
 * ⚠️ THE MAXIMUM IS NEW AND WAS ENFORCED NOWHERE ON THE CLIENT. The API has
 *    bounded these fields at 128 since registration was written, and Phase 5
 *    bounded every other credential field to match — so a longer password was
 *    always going to come back as a 400 the user could not act on, after they
 *    had typed it twice. Failing in the browser, against the same number, is
 *    the only version of this that explains itself.
 */

/** Mirrors `_MIN_PASSWORD` / `_MAX_PASSWORD` in `backend/app/auth/schemas.py`. */
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 128

export type PasswordRule = {
  /** Message key under the `auth.password` namespace, as `rule_${key}`. */
  key: string
  test: (value: string) => boolean
  /** Whether failing it blocks submission, or is only shown as advice. */
  gates: boolean
}

export const PASSWORD_RULES: readonly PasswordRule[] = [
  { key: 'length', test: (v) => v.length >= PASSWORD_MIN, gates: true },
  // Gates, unlike the two below: the server rejects it, so submitting is a
  // guaranteed round trip to a 400.
  { key: 'maxLength', test: (v) => v.length <= PASSWORD_MAX, gates: true },
  { key: 'uppercase', test: (v) => /[A-Z]/.test(v), gates: false },
  { key: 'number', test: (v) => /[0-9\W_]/.test(v), gates: false },
] as const

export type PasswordCheck = PasswordRule & { met: boolean }

/**
 * Evaluate every rule against a candidate.
 *
 * ⚠️ `maxLength` is reported as MET for an empty field, like every other rule,
 * so an untouched form does not open showing a failure the user has not caused.
 */
export function checkPassword(value: string): PasswordCheck[] {
  return PASSWORD_RULES.map((rule) => ({ ...rule, met: rule.test(value) }))
}

/** True when nothing that gates submission is failing. */
export function passwordIsSubmittable(value: string): boolean {
  return checkPassword(value).every((check) => !check.gates || check.met)
}
