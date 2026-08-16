'use client'

import { useCallback, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthField } from '@/components/auth/AuthField'
import { AuthShell } from '@/components/auth/AuthShell'
import { CountdownReadout } from '@/components/auth/Countdown'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { Turnstile } from '@/components/auth/Turnstile'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowIcon, LockIcon, MailIcon, SecurityIcon } from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { adminLogin } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import {
  setEnrollmentHandoff,
  setPendingChallenge,
  setUnverifiedEmail,
} from '@/lib/auth/challenge'

/**
 * Administrator sign-in (prd.md FR-A2a).
 *
 * ⚠️ THE UNLISTED URL IS NOT A SECURITY CONTROL, and neither is this component.
 *    `proxy.ts` rewrites a server-only secret path here so the page is not
 *    listed anywhere; the actual gate is `POST /api/auth/admin/login`, which
 *    refuses every non-administrator with the same 401 as a wrong password.
 *    Somebody who learns the path gains nothing. Do not add a role check here
 *    and consider anything protected — the same rule as `SessionGuard`.
 *
 * WHY THIS IS A SEPARATE COMPONENT AND NOT A PROP ON `LoginForm`: the public
 * form calls `login()` and this one calls `adminLogin()`. A shared component
 * with a boolean would put the choice of endpoint behind a value that a future
 * refactor could thread in from a URL or a query string, and the whole point of
 * the split is that the endpoint is fixed at the route. What IS shared is
 * everything that carries risk — the challenge handoffs, the error mapping and
 * the captcha reset below are the same code paths, imported not copied.
 *
 * Deliberately absent, and each absence is a decision:
 *  - no "create an account" link. Administrators are provisioned by SQL run by
 *    the repository owner; `app_user_insert` refuses `role = 'admin'` outright.
 *  - no "forgot password" link. That flow is public and address-keyed, so
 *    linking it from here would tell anyone who found this page that the
 *    address they are probing reaches a real reset e-mail.
 *  - no language switcher and no brand hero. This is an operations door, not a
 *    marketing surface.
 */
export function AdminLoginForm() {
  const t = useTranslations('auth.adminLogin')
  const te = useTranslations('auth.errors')
  const tt = useTranslations('auth.turnstile')
  const router = useRouter()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaNonce, setCaptchaNonce] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [lockedUntilMs, setLockedUntilMs] = useState<number | null>(null)
  const [retryAtMs, setRetryAtMs] = useState<number | null>(null)

  const clearLock = useCallback(() => setLockedUntilMs(null), [])
  const clearRateLimit = useCallback(() => setRetryAtMs(null), [])

  const rateLimited = retryAtMs !== null
  const canSubmit =
    email.trim() !== '' &&
    password !== '' &&
    captchaToken !== null &&
    !submitting &&
    !rateLimited

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})

    try {
      const result = await adminLogin({
        email: email.trim(),
        password,
        turnstile_token: captchaToken ?? '',
      })

      // A 200 is never a credential failure here either: it means the password
      // was right and the journey is unfinished. The continuations are the
      // SHARED ones — /auth/2fa/verify and /auth/2fa/resend are not segregated,
      // because the challenge token issued above is already bound to this user.
      switch (result.status) {
        case 'two_factor_required':
          setPendingChallenge({
            token: result.pending_token,
            method: result.method,
            expiresAtMs: Date.now() + result.expires_in * 1000,
            email: email.trim(),
          })
          router.push('/login/2fa')
          return

        case 'two_factor_enrollment_required':
          setEnrollmentHandoff({
            token: result.enrollment_token,
            expiresAtMs: Date.now() + result.expires_in * 1000,
            email: email.trim(),
          })
          router.push('/onboarding/2fa')
          return

        case 'email_verification_required':
          setUnverifiedEmail(email.trim())
          router.push('/onboarding/email')
          return
      }
      // No `finally`: every branch above navigates away, and re-enabling the
      // button mid-transition invites a second submission.
    } catch (error) {
      // A failed submit means siteverify consumed the token. Drop it and force a
      // fresh solve; never re-enable the button with a dead token.
      setCaptchaToken(null)
      setCaptchaNonce((n) => n + 1)
      setSubmitting(false)

      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
        return
      }

      if (error.status === 423) {
        const until = error.details.locked_until
        setLockedUntilMs(typeof until === 'string' ? Date.parse(until) : null)
        return
      }

      if (error.code === 'RATE_LIMITED') {
        const seconds =
          typeof error.details.retry_after === 'number' ? error.details.retry_after : 60
        setRetryAtMs(Date.now() + seconds * 1000)
        return
      }

      if (error.code === 'VALIDATION_ERROR') {
        setFieldErrors(error.fieldErrors())
        return
      }

      if (error.code === 'CAPTCHA_FAILED') {
        setFormError(te('captchaFailed'))
        return
      }

      // THE SAME NEUTRAL MESSAGE the public form shows, deliberately reusing its
      // key rather than writing an admin-specific one. "You are not an
      // administrator" would be a true statement and an enumeration oracle.
      setFormError(error.status === 401 ? te('badCredentials') : te('generic'))
    }
  }

  return (
    <AuthShell>
      {lockedUntilMs !== null ? (
        <LockedPanel lockedUntilMs={lockedUntilMs} onExpire={clearLock} />
      ) : (
        <div className="motion-safe:animate-fade-in-up">
          <div className="mb-8 text-center">
            <div className="mb-5 inline-flex h-14 w-14 items-center justify-center rounded-full bg-tertiary-container text-on-tertiary-container">
              <SecurityIcon className="h-7 w-7" />
            </div>
            <h1 className="mb-2 font-headline text-headline-md text-on-surface">
              {t('title')}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </div>

          <form onSubmit={submit} className="space-y-6" noValidate>
            {formError && <FormBanner>{formError}</FormBanner>}

            {rateLimited && (
              <FormBanner>
                <span className="flex flex-wrap items-center gap-1">
                  {te('rateLimitedIn')}
                  <CountdownReadout
                    targetMs={retryAtMs}
                    onExpire={clearRateLimit}
                    className="font-semibold"
                  />
                </span>
              </FormBanner>
            )}

            <AuthField
              label={t('emailLabel')}
              name="email"
              type="email"
              autoComplete="username"
              placeholder={t('emailPlaceholder')}
              icon={<MailIcon className="h-5 w-5" />}
              value={email}
              onChange={setEmail}
              error={fieldErrors.email}
              required
              disabled={submitting}
            />

            <AuthField
              label={t('passwordLabel')}
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              icon={<LockIcon className="h-5 w-5" />}
              value={password}
              onChange={setPassword}
              error={fieldErrors.password}
              required
              disabled={submitting}
            />

            <div className="mt-1">
              <p className="mb-1 text-body-sm text-on-surface-variant">{tt('label')}</p>
              <Turnstile
                onVerify={setCaptchaToken}
                onExpired={() => setCaptchaToken(null)}
                resetNonce={captchaNonce}
              />
            </div>

            <button
              type="submit"
              disabled={!canSubmit}
              className="flex w-full items-center justify-center rounded border border-transparent bg-primary px-4 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-on-primary-fixed-variant active:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? t('submitting') : t('submit')}
              <ArrowIcon className="ms-2 h-[18px] w-[18px] rtl:-scale-x-100" />
            </button>
          </form>

          <p className="mt-6 text-center text-body-sm text-on-surface-variant">{t('notice')}</p>
        </div>
      )}
    </AuthShell>
  )
}
