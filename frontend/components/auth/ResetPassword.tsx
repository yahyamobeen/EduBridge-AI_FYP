'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthField } from '@/components/auth/AuthField'
import { AuthPanel, AuthShell } from '@/components/auth/AuthShell'
import { FormBanner } from '@/components/ui/FormFeedback'
import {
  AlertCircleIcon,
  ArrowIcon,
  CheckCircleIcon,
  HistoryIcon,
  LockIcon,
} from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { resetPassword } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'

type State = 'form' | 'done' | 'expired' | 'invalid'

/**
 * The three requirements the prototype lists.
 *
 * ADVISORY, NOT ENFORCED — except the length rule. No source states the real
 * password policy (plan assumption A6), so the client cannot be the authority
 * on it: enforcing rules stricter than the server's would block valid
 * passwords, and the server's `VALIDATION_ERROR` governs either way. They are
 * shown live because a checklist that fills in as you type is genuinely useful;
 * they are not a gate because the client does not know the rule.
 */
const RULES = [
  { key: 'length', test: (v: string) => v.length >= 8, gates: true },
  { key: 'uppercase', test: (v: string) => /[A-Z]/.test(v), gates: false },
  { key: 'number', test: (v: string) => /[0-9\W_]/.test(v), gates: false },
] as const

export function ResetPassword({ token }: { token: string | null }) {
  const t = useTranslations('auth.resetPassword')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const [state, setState] = useState<State>(token === null ? 'invalid' : 'form')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const checks = RULES.map((rule) => ({ ...rule, met: rule.test(password) }))
  const mismatch = confirm !== '' && confirm !== password
  const canSubmit =
    !submitting &&
    checks.every((c) => !c.gates || c.met) &&
    confirm === password &&
    confirm !== ''

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (token === null || !canSubmit) return

    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})

    try {
      await resetPassword({ token, new_password: password })
      setState('done')
    } catch (error) {
      setSubmitting(false)
      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
        return
      }
      if (error.code === 'TOKEN_EXPIRED') setState('expired')
      else if (error.code === 'INVALID_TOKEN') setState('invalid')
      else if (error.code === 'VALIDATION_ERROR') setFieldErrors(error.fieldErrors())
      else if (error.code === 'RATE_LIMITED') setFormError(te('rateLimited'))
      else setFormError(te('generic'))
    }
  }

  if (state === 'done') {
    return (
      <AuthShell>
        <AuthPanel
          tone="success"
          icon={<CheckCircleIcon className="h-8 w-8" />}
          title={t('doneTitle')}
          body={t('doneBody')}
        >
          <button
            type="button"
            onClick={() => router.replace('/login')}
            className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container"
          >
            {t('signIn')}
          </button>
        </AuthPanel>
      </AuthShell>
    )
  }

  if (state !== 'form') {
    const expired = state === 'expired'
    return (
      <AuthShell>
        <AuthPanel
          tone={expired ? 'neutral' : 'error'}
          icon={
            expired ? (
              <HistoryIcon className="h-8 w-8" />
            ) : (
              <AlertCircleIcon className="h-8 w-8" />
            )
          }
          title={expired ? t('expiredTitle') : t('invalidTitle')}
          body={expired ? t('expiredBody') : t('invalidBody')}
        >
          <button
            type="button"
            onClick={() => router.replace('/forgot-password')}
            className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container"
          >
            {t('requestNew')}
          </button>
        </AuthPanel>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="text-center">
          <h1 className="mb-2 font-headline text-headline-md text-on-surface">{t('title')}</h1>
          <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
        </div>

        <form onSubmit={submit} className="space-y-6" noValidate>
          {formError && <FormBanner>{formError}</FormBanner>}

          <div className="space-y-3">
            <AuthField
              label={t('newPassword')}
              name="new_password"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              icon={<LockIcon className="h-5 w-5" />}
              value={password}
              onChange={setPassword}
              error={fieldErrors.new_password}
              required
              disabled={submitting}
            />

            <ul className="space-y-2 rounded border border-outline-variant/50 bg-surface-container-highest p-3">
              <li className="mb-1 text-label-caps uppercase text-outline">{t('rulesTitle')}</li>
              {checks.map((check) => (
                <li
                  key={check.key}
                  className={`flex items-center gap-2 text-body-sm ${
                    check.met ? 'text-on-surface' : 'text-on-surface-variant'
                  }`}
                >
                  {/* Met-ness is carried by the icon and the text weight, not by
                      colour alone (prd.md A11Y-1a). */}
                  {check.met ? (
                    <CheckCircleIcon className="h-4 w-4 shrink-0 text-status-verified" />
                  ) : (
                    <span
                      aria-hidden="true"
                      className="h-4 w-4 shrink-0 rounded-full border border-outline"
                    />
                  )}
                  <span>{t(`rule_${check.key}`)}</span>
                  <span className="sr-only">{check.met ? t('ruleMet') : t('ruleNotMet')}</span>
                </li>
              ))}
            </ul>
          </div>

          <AuthField
            label={t('confirmPassword')}
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            placeholder="••••••••"
            icon={<LockIcon className="h-5 w-5" />}
            value={confirm}
            onChange={setConfirm}
            error={mismatch ? t('mismatch') : undefined}
            required
            disabled={submitting}
          />

          <button
            type="submit"
            disabled={!canSubmit}
            className="group flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-3 text-body-lg font-semibold text-on-primary transition-colors hover:bg-primary-container hover:text-on-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t('updating') : t('submit')}
            <ArrowIcon className="h-5 w-5 transition-transform group-hover:translate-x-1 rtl:-scale-x-100" />
          </button>
        </form>
      </div>
    </AuthShell>
  )
}
