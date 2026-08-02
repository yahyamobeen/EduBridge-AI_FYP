'use client'

import { useCallback, useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthFooterLinks } from '@/components/auth/AuthFooterLinks'
import { CodeInput } from '@/components/auth/CodeInput'
import { CountdownReadout } from '@/components/auth/Countdown'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { ErrorText, FormBanner } from '@/components/ui/FormFeedback'
import {
  ArrowIcon,
  ArrowLeftIcon,
  ChevronRightIcon,
  KeyIcon,
  MailIcon,
  SecurityIcon,
} from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { getMe, startSession, twoFactorVerify } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { TwoFactorMethod, TwoFactorType } from '@/lib/api/types'
import { clearAllChallenges, getPendingChallenge } from '@/lib/auth/challenge'
import { dashboardFor, pendingOnboardingRoute } from '@/lib/auth/onboarding'

/** 6 digits for a one-time code; 8 alphanumerics for a backup code (decision 9). */
const CODE_LENGTH: Record<TwoFactorType, number> = {
  totp: 6,
  email_otp: 6,
  backup_code: 8,
}

/** Local masking for display only — the address came from this browser. */
function maskEmail(email: string): string {
  const [name = '', domain = ''] = email.split('@')
  const head = name.slice(0, 1)
  return `${head}${'*'.repeat(Math.max(2, name.length - 1))}@${domain}`
}

type Screen = 'code' | 'options' | 'locked' | 'expired'

/**
 * The second factor at sign-in.
 *
 * Three things differ from the prototype, each for a reason worth keeping:
 *
 *  1. It opens on the method the SERVER returned with `two_factor_required`,
 *     not on TOTP. A student enrolled in email OTP -- the option that exists
 *     precisely for students without a smartphone (prd.md NFR-2) -- would
 *     otherwise land on a screen asking for an authenticator app they do not
 *     have.
 *
 *  2. Switching method is real. The prototype's `selectMethod()` fires an
 *     `alert()` and changes a placeholder; here it changes the `type` sent to
 *     the server and the mask of the field.
 *
 *  3. The lockout is driven by `details.locked_until` from the 423, not by
 *     counting failures in this tab. The prototype's local counter resets on
 *     reload, which is a demonstration of the visual rather than the rule.
 *
 * CONTRACT GAP, deliberately not papered over: the prototype offers "Email OTP
 * — send a code to s***@…" as an alternative to TOTP, but no endpoint sends an
 * OTP during a challenge, and none resends one. So the alternative offered here
 * is the backup code, which needs no send step because enrolment already handed
 * the codes over. Raised with Muneeb; if a send endpoint lands, email OTP joins
 * this list unchanged.
 */
export function TwoFactorChallenge() {
  const t = useTranslations('auth.twoFactor')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const challenge = getPendingChallenge()

  const [type, setType] = useState<TwoFactorType>(challenge?.method ?? 'totp')
  const [code, setCode] = useState('')
  const [screen, setScreen] = useState<Screen>('code')
  const [submitting, setSubmitting] = useState(false)
  const [codeError, setCodeError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [lockedUntilMs, setLockedUntilMs] = useState<number | null>(null)
  const [shaking, setShaking] = useState(false)
  const [focusKey, setFocusKey] = useState(0)

  /**
   * No challenge in memory means this screen was opened directly, or reloaded
   * after the token was lost with the page. Either way there is nothing to
   * verify, so it returns to sign-in rather than showing a form that cannot
   * succeed. In an effect because navigating during render is not allowed.
   */
  useEffect(() => {
    if (challenge === null) router.replace('/login')
  }, [challenge, router])

  const onExpiry = useCallback(() => setScreen('expired'), [])
  const onLockExpiry = useCallback(() => {
    setLockedUntilMs(null)
    setScreen('code')
  }, [])

  if (challenge === null) return null

  const length = CODE_LENGTH[type]
  const isBackup = type === 'backup_code'
  const enrolled: TwoFactorMethod = challenge.method

  function switchTo(next: TwoFactorType) {
    setType(next)
    setCode('')
    setCodeError(null)
    setFormError(null)
    setScreen('code')
    setFocusKey((k) => k + 1)
  }

  function reject(message: string) {
    setCodeError(message)
    setCode('')
    setShaking(true)
    setFocusKey((k) => k + 1)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (challenge === null || code.length !== length) return

    setSubmitting(true)
    setCodeError(null)
    setFormError(null)

    try {
      const result = await twoFactorVerify({
        pending_token: challenge.token,
        code,
        type,
      })

      // Order matters: the session is stored before the spent challenge is
      // dropped, so a failure between the two cannot leave the user with
      // neither credential.
      startSession(result.access_token, result.expires_in)
      clearAllChallenges()

      const next = pendingOnboardingRoute(result.onboarding_state)
      if (next !== null) {
        router.replace(next)
        return
      }
      // Fully onboarded: the destination depends on the role, which this
      // response does not carry, so ask the identity endpoint for it.
      const me = await getMe()
      router.replace(dashboardFor(me.role))
      return
    } catch (error) {
      setSubmitting(false)

      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
        return
      }

      if (error.code === 'TWO_FACTOR_INVALID') {
        reject(te('invalidCode'))
        return
      }

      if (error.code === 'PENDING_TOKEN_EXPIRED') {
        setScreen('expired')
        return
      }

      if (error.status === 423) {
        const until = error.details.locked_until
        setLockedUntilMs(typeof until === 'string' ? Date.parse(until) : null)
        setScreen('locked')
        return
      }

      if (error.code === 'RATE_LIMITED') {
        setFormError(te('rateLimited'))
        return
      }

      setFormError(te('generic'))
    }
  }

  return (
    <div className="relative flex flex-grow items-center justify-center overflow-hidden p-margin-mobile md:p-margin-desktop">
      {/* Prototype backdrop: three blurred discs, measured at 80/100/60px blur. */}
      <div
        className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
        aria-hidden="true"
      >
        <div className="absolute -end-[5%] -top-[10%] h-[40%] w-[40%] rounded-full bg-primary-fixed-dim/20 blur-[80px]" />
        <div className="absolute -bottom-[10%] -start-[10%] h-[50%] w-[50%] rounded-full bg-student-blue/40 blur-[100px]" />
        <div className="absolute start-[20%] top-[40%] h-[30%] w-[30%] rounded-full bg-surface-container-high/50 blur-[60px]" />
      </div>

      <div className="relative z-10 w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded bg-primary-container text-on-primary shadow-sm">
              <SecurityIcon className="h-6 w-6" />
            </div>
            <span className="font-headline text-headline-md text-primary">{t('brand')}</span>
          </div>
        </div>

        <div className="relative overflow-hidden rounded-md border border-outline-variant bg-surface-container-lowest p-8 shadow-sm transition-all duration-300">
          {screen === 'locked' && (
            <LockedPanel lockedUntilMs={lockedUntilMs} onExpire={onLockExpiry} />
          )}

          {screen === 'expired' && (
            <div
              role="alert"
              className="flex flex-col items-center space-y-6 py-4 text-center motion-safe:animate-fade-in-up"
            >
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-container text-on-surface-variant">
                <SecurityIcon className="h-8 w-8" />
              </div>
              <div>
                <h2 className="mb-2 font-headline text-headline-md text-on-surface">
                  {t('expiredTitle')}
                </h2>
                <p className="text-body-md text-on-surface-variant">{t('expiredBody')}</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  clearAllChallenges()
                  router.replace('/login')
                }}
                className="w-full rounded bg-primary-container px-4 py-4 text-label-caps uppercase tracking-wider text-on-primary transition-colors hover:bg-primary"
              >
                {t('backToSignIn')}
              </button>
            </div>
          )}

          {screen === 'options' && (
            <div className="flex flex-col space-y-6 motion-safe:animate-fade-in-up">
              <div className="mb-2 flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => setScreen('code')}
                  aria-label={t('back')}
                  className="flex items-center justify-center rounded-full p-2 text-on-surface-variant transition-colors hover:bg-surface-variant"
                >
                  <ArrowLeftIcon className="h-5 w-5 rtl:-scale-x-100" />
                </button>
                <h2 className="font-headline text-headline-md text-on-surface">
                  {t('optionsTitle')}
                </h2>
              </div>
              <p className="text-body-sm text-on-surface-variant">{t('optionsBody')}</p>

              <div className="space-y-3">
                {isBackup ? (
                  <MethodOption
                    icon={<MailIcon className="h-5 w-5" />}
                    title={t(enrolled === 'totp' ? 'methodTotpTitle' : 'methodEmailTitle')}
                    body={
                      enrolled === 'totp'
                        ? t('methodTotpBody')
                        : t('methodEmailBody', { email: maskEmail(challenge.email) })
                    }
                    onSelect={() => switchTo(enrolled)}
                  />
                ) : (
                  <MethodOption
                    icon={<KeyIcon className="h-5 w-5" />}
                    title={t('methodBackupTitle')}
                    body={t('methodBackupBody')}
                    onSelect={() => switchTo('backup_code')}
                  />
                )}
              </div>
            </div>
          )}

          {screen === 'code' && (
            <div className="flex flex-col space-y-6">
              <div className="text-center">
                <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
                  {t('title')}
                </h1>
                <p className="text-body-md text-on-surface-variant">
                  {isBackup
                    ? t('promptBackup')
                    : type === 'email_otp'
                      ? t('promptEmail', { email: maskEmail(challenge.email) })
                      : t('promptTotp')}
                </p>
              </div>

              <form onSubmit={submit} className="space-y-6" noValidate>
                {formError && <FormBanner>{formError}</FormBanner>}

                <div
                  className={shaking ? 'motion-safe:animate-shake' : undefined}
                  onAnimationEnd={() => setShaking(false)}
                >
                  <CodeInput
                    id="two-factor-code"
                    label={t('codeLabel')}
                    value={code}
                    onChange={setCode}
                    length={length}
                    alphanumeric={isBackup}
                    invalid={codeError !== null}
                    describedBy={codeError !== null ? 'two-factor-code-error' : undefined}
                    focusKey={focusKey}
                    disabled={submitting}
                  />
                  {codeError !== null && (
                    <div className="mt-2 flex justify-center">
                      <ErrorText id="two-factor-code-error">{codeError}</ErrorText>
                    </div>
                  )}
                </div>

                {/*
                  The challenge itself expires. The prototype has no such
                  indicator, so a student typing slowly on a shared phone would
                  simply be told "invalid" with no explanation.
                */}
                {!isBackup && (
                  <p className="flex items-center justify-center gap-1.5 text-body-sm text-on-surface-variant">
                    {t('expiresIn')}
                    <CountdownReadout targetMs={challenge.expiresAtMs} onExpire={onExpiry} />
                  </p>
                )}

                <button
                  type="submit"
                  disabled={submitting || code.length !== length}
                  className="flex w-full items-center justify-center gap-2 rounded bg-primary-container px-4 py-4 text-label-caps uppercase tracking-wider text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? t('verifying') : t('verify')}
                  <ArrowIcon className="h-4 w-4 rtl:-scale-x-100" />
                </button>
              </form>

              <div className="border-t border-surface-variant pt-4 text-center">
                <button
                  type="button"
                  onClick={() => setScreen('options')}
                  className="text-body-sm text-primary transition-colors hover:text-primary-container"
                >
                  {t('tryAnotherWay')}
                </button>
              </div>
            </div>
          )}
        </div>

        <AuthFooterLinks />
      </div>
    </div>
  )
}

function MethodOption({
  icon,
  title,
  body,
  onSelect,
}: {
  icon: React.ReactNode
  title: string
  body: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group flex w-full items-center justify-between rounded border border-outline-variant p-4 text-start transition-all hover:border-primary-container hover:bg-surface-container-low"
    >
      <span className="flex items-center gap-4">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-container text-primary-container transition-colors group-hover:bg-primary-container group-hover:text-on-primary">
          {icon}
        </span>
        <span className="flex flex-col">
          <span className="font-headline text-body-md font-semibold text-on-surface">
            {title}
          </span>
          <span className="text-body-sm text-on-surface-variant">{body}</span>
        </span>
      </span>
      <ChevronRightIcon className="h-5 w-5 shrink-0 text-outline-variant group-hover:text-primary-container rtl:-scale-x-100" />
    </button>
  )
}
