'use client'

import { useCallback, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthField } from '@/components/auth/AuthField'
import { CountdownReadout } from '@/components/auth/Countdown'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { LanguageSwitcher } from '@/components/layout/LanguageSwitcher'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowIcon, LockIcon, MailIcon, TeachIcon } from '@/components/ui/Icon'
import { Link, useRouter } from '@/i18n/navigation'
import { login } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import {
  setEnrollmentHandoff,
  setPendingChallenge,
  setUnverifiedEmail,
} from '@/lib/auth/challenge'

/**
 * Sign-in.
 *
 * THE ONE RULE THAT SHAPES THIS SCREEN: a 200 from /auth/login is never a
 * failure. It means the password was correct and the journey is unfinished, so
 * every status branches forward to the step that finishes it. Only a 401 is a
 * credential error, and it is deliberately one neutral message for both "no
 * such account" and "wrong password" -- distinguishing them would let anyone
 * enumerate registered addresses (tdd.md §3.1, §6.3).
 *
 * The prototype's Google and Microsoft buttons are NOT built: no endpoint
 * accepts them and prd.md §623 puts SSO outside v1, so they would be two
 * controls that do nothing. The schema and documents carry the OAuth design
 * (decision 10) for when it is implemented.
 */
export function LoginForm() {
  const t = useTranslations('auth.login')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [lockedUntilMs, setLockedUntilMs] = useState<number | null>(null)
  const [retryAtMs, setRetryAtMs] = useState<number | null>(null)

  const clearLock = useCallback(() => setLockedUntilMs(null), [])
  const clearRateLimit = useCallback(() => setRetryAtMs(null), [])

  const rateLimited = retryAtMs !== null
  const canSubmit = email.trim() !== '' && password !== '' && !submitting && !rateLimited

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})

    try {
      const result = await login({ email: email.trim(), password })

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
          // The response carries a MASKED address, which /auth/email/resend
          // cannot act on. What the user typed is the only usable value.
          setUnverifiedEmail(email.trim())
          router.push('/onboarding/email')
          return
      }
      // No `finally`: on every branch above the screen is navigating away, and
      // re-enabling the button mid-transition invites a second submission.
    } catch (error) {
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

      // Every other 401 collapses into the same neutral message, on purpose.
      setFormError(error.status === 401 ? te('badCredentials') : te('generic'))
    }
  }

  return (
    /* min-h-screen, not viewport-minus-nav: this group renders no nav. */
    <div className="relative flex min-h-screen w-full">
      {/*
        Left half: brand panel, desktop only, content anchored to the bottom.

        The prototype layers a stock photograph from a Google CDN under the blue
        gradient. It is not reproduced: it is a third-party request in the
        critical path on mobile data (prd.md A11Y-2), the CSP in next.config.mjs
        allows `img-src 'self' data:` only, and the asset is a generated
        placeholder with no licence attached. The layer stack, the dot pattern,
        the gradient and the type are the prototype's, measured.
      */}
      <section className="relative hidden w-1/2 items-end justify-center overflow-hidden bg-surface-container-high lg:flex">
        <div className="dot-pattern-primary absolute inset-0 opacity-50" aria-hidden="true" />
        <div
          className="absolute inset-0 bg-[radial-gradient(120%_90%_at_50%_115%,theme(colors.primary)_0%,transparent_70%)]"
          aria-hidden="true"
        />
        <div
          className="absolute inset-0 bg-gradient-to-t from-primary/80 via-primary/30 to-transparent"
          aria-hidden="true"
        />

        <div className="relative z-10 w-full max-w-2xl p-margin-desktop text-on-primary">
          <div className="mb-gutter">
            <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-outline-variant/30 bg-surface-container-lowest/20 px-4 py-2 text-label-caps uppercase text-on-primary backdrop-blur-sm">
              <TeachIcon className="h-4 w-4 motion-safe:animate-pulse" />
              {t('heroBadge')}
            </span>
            <h1 className="mb-4 font-headline text-headline-lg text-white drop-shadow-md">
              {t('heroTitle')}
            </h1>
            <p className="max-w-lg text-body-lg text-primary-fixed-dim">{t('heroBody')}</p>
          </div>
        </div>
      </section>

      {/* Right half: the form. Full width until lg, as in the prototype. */}
      <section className="relative z-10 flex w-full items-center justify-center bg-background p-margin-mobile lg:w-1/2 lg:p-margin-desktop">
        <div className="w-full max-w-md">
          <div className="mb-10 text-center">
            <div className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-md bg-primary-container text-on-primary-container shadow-sm">
              <TeachIcon className="h-8 w-8" />
            </div>
            <h2 className="mb-2 font-headline text-headline-md text-on-background">
              {t('title')}
            </h2>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </div>

          <div className="rounded-md border border-outline-variant/50 bg-surface-container-lowest p-6 shadow-sm md:p-8">
            {lockedUntilMs !== null ? (
              <LockedPanel lockedUntilMs={lockedUntilMs} onExpire={clearLock} />
            ) : (
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
                  labelAction={
                    <Link
                      href="/forgot-password"
                      className="text-body-sm font-semibold text-primary transition-colors hover:text-on-primary-fixed-variant"
                    >
                      {t('forgotPassword')}
                    </Link>
                  }
                />

                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="flex w-full items-center justify-center rounded border border-transparent bg-primary px-4 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-on-primary-fixed-variant active:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? t('submitting') : t('submit')}
                  {/* 18px, matching the prototype's icon glyph: it, not the
                      12px label, is what sets the button's 44px height. */}
                  <ArrowIcon className="ms-2 h-[18px] w-[18px] rtl:-scale-x-100" />
                </button>
              </form>
            )}
          </div>

          {/*
            The prototype says "Sign up as Student", which sends a teacher or a
            parent to the wrong form. It points at the role chooser instead.
          */}
          <p className="mt-8 text-center text-body-md text-on-surface-variant">
            {t('noAccount')}{' '}
            <Link
              href="/signup"
              className="font-semibold text-primary transition-colors hover:text-on-primary-fixed-variant"
            >
              {t('createAccount')}
            </Link>
          </p>

          {/*
            This group renders no top nav, so without the switcher here there is
            no way to change language on the sign-in screen — the one most often
            reached cold, and the one where an Urdu-first user most needs it
            (prd.md I18N-1).
          */}
          <div className="mt-8 flex justify-center">
            <LanguageSwitcher />
          </div>
        </div>
      </section>
    </div>
  )
}
