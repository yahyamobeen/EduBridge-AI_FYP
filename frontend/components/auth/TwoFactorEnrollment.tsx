'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthShell } from '@/components/auth/AuthShell'
import { BackupCodes } from '@/components/auth/BackupCodes'
import { CodeInput } from '@/components/auth/CodeInput'
import { CountdownReadout } from '@/components/auth/Countdown'
import { LockedPanel } from '@/components/auth/LockedPanel'
import { ErrorText, FormBanner } from '@/components/ui/FormFeedback'
import {
  ArrowIcon,
  ArrowLeftIcon,
  ChevronRightIcon,
  MailIcon,
  SecurityIcon,
} from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { startSession, twoFactorConfirm, twoFactorEnroll } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { TwoFactorEnrollResponse, TwoFactorMethod } from '@/lib/api/types'
import { clearAllChallenges, getEnrollmentHandoff } from '@/lib/auth/challenge'
import { pendingOnboardingRoute } from '@/lib/auth/onboarding'

type Step = 'choose' | 'setup' | 'codes' | 'locked'

/**
 * Mandatory second-factor enrolment (FR-A4 / SEC-14).
 *
 * There is NO prototype for this screen — the mockup set skips from login
 * straight to the challenge, which is one of the gaps the audit surfaced. It is
 * therefore built in the challenge screen's visual language, through the shared
 * `AuthShell`, rather than inventing a third look.
 *
 * THE REVIEW GATE ON THIS SCREEN IS EQUAL PROMINENCE. Both methods render
 * through one component, at the same size, in the same button variant, with
 * neither preselected and neither behind a disclosure. Burying email OTP as the
 * "advanced" or "no smartphone?" option would lock out exactly the students
 * `prd.md` §3.1 and NFR-2 describe — the ones sharing a family phone.
 *
 * The backup codes are shown ONCE. `beforeunload` is unreliable on mobile
 * Safari, so the real safeguard is the acknowledgement checkbox that gates the
 * continue button, not a warning the browser may never display.
 */
export function TwoFactorEnrollment() {
  const t = useTranslations('auth.enroll')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  /**
   * Captured ONCE for the life of this screen, not re-read each render.
   *
   * Confirmation calls `clearAllChallenges()` so a spent token cannot be
   * replayed. Re-reading the store after that would find `null` and fire the
   * "no token, go to sign in" guard below — blanking the backup codes the user
   * has not saved yet, and racing a redirect to /login against the real
   * destination. The token is a fact about how this screen was ENTERED.
   */
  const [handoff] = useState(getEnrollmentHandoff)

  const [step, setStep] = useState<Step>('choose')
  // The chosen method is read back off the enrolment RESPONSE rather than kept
  // separately, so the screen can never disagree with what the server enrolled.
  const [enrollment, setEnrollment] = useState<TwoFactorEnrollResponse | null>(null)
  const [otpExpiresAtMs, setOtpExpiresAtMs] = useState<number | null>(null)
  const [code, setCode] = useState('')
  const [backupCodes, setBackupCodes] = useState<string[]>([])
  const [nextRoute, setNextRoute] = useState<string | null>(null)

  const [starting, setStarting] = useState<TwoFactorMethod | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [codeError, setCodeError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [lockedUntilMs, setLockedUntilMs] = useState<number | null>(null)
  const [shaking, setShaking] = useState(false)
  const [focusKey, setFocusKey] = useState(0)
  const [resent, setResent] = useState(false)

  /**
   * No enrollment token means this was opened directly, or reloaded after the
   * token was lost with the page. Enrolment cannot start without it, so the
   * user goes back to sign in and picks the journey up again.
   */
  useEffect(() => {
    if (handoff === null) router.replace('/login')
  }, [handoff, router])

  if (handoff === null) return null

  async function start(chosen: TwoFactorMethod, isResend = false) {
    if (handoff === null) return
    setStarting(chosen)
    setFormError(null)
    try {
      const result = await twoFactorEnroll({
        method: chosen,
        enrollment_token: handoff.token,
      })
      setEnrollment(result)
      setOtpExpiresAtMs(
        result.method === 'email_otp' ? Date.now() + result.expires_in * 1000 : null,
      )
      if (isResend) setResent(true)
      setStep('setup')
      setFocusKey((k) => k + 1)
    } catch (error) {
      setFormError(
        error instanceof ApiError && error.code === 'RATE_LIMITED'
          ? te('rateLimited')
          : te('generic'),
      )
    } finally {
      setStarting(null)
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault()
    if (handoff === null || code.length !== 6) return

    setSubmitting(true)
    setCodeError(null)
    setFormError(null)

    try {
      const result = await twoFactorConfirm({ code, enrollment_token: handoff.token })

      // The session is stored before the spent enrolment token is dropped, so a
      // failure between the two cannot leave the user holding neither.
      startSession(result.access_token, result.expires_in)
      clearAllChallenges()

      setBackupCodes(result.backup_codes)
      // Where to go once the codes are acknowledged. Computed now, while the
      // response is in hand -- not on the button, which would need the state again.
      setNextRoute(pendingOnboardingRoute(result.onboarding_state) ?? '/dashboard')
      setStep('codes')
    } catch (error) {
      setSubmitting(false)

      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
        return
      }
      if (error.code === 'TWO_FACTOR_INVALID') {
        setCodeError(te('invalidCode'))
        setCode('')
        setShaking(true)
        setFocusKey((k) => k + 1)
        return
      }
      if (error.code === 'PENDING_TOKEN_EXPIRED') {
        clearAllChallenges()
        router.replace('/login')
        return
      }
      if (error.status === 423) {
        const until = error.details.locked_until
        setLockedUntilMs(typeof until === 'string' ? Date.parse(until) : null)
        setStep('locked')
        return
      }
      setFormError(error.code === 'RATE_LIMITED' ? te('rateLimited') : te('generic'))
    }
  }

  if (step === 'locked') {
    return (
      <AuthShell>
        <LockedPanel
          lockedUntilMs={lockedUntilMs}
          onExpire={() => {
            setLockedUntilMs(null)
            setStep('setup')
          }}
        />
      </AuthShell>
    )
  }

  if (step === 'codes') {
    return (
      <AuthShell>
        <BackupCodes
          codes={backupCodes}
          onContinue={() => router.replace(nextRoute ?? '/dashboard')}
        />
      </AuthShell>
    )
  }

  if (step === 'setup' && enrollment !== null) {
    return (
      <AuthShell>
        <div className="flex flex-col space-y-6">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => {
                setStep('choose')
                setCode('')
                setCodeError(null)
                setResent(false)
              }}
              aria-label={t('back')}
              className="flex items-center justify-center rounded-full p-2 text-on-surface-variant transition-colors hover:bg-surface-variant"
            >
              <ArrowLeftIcon className="h-5 w-5 rtl:-scale-x-100" />
            </button>
            <h1 className="font-headline text-headline-md text-on-surface">
              {enrollment.method === 'totp' ? t('totpTitle') : t('emailTitle')}
            </h1>
          </div>

          {formError && <FormBanner>{formError}</FormBanner>}

          {enrollment.method === 'totp' ? (
            <div className="space-y-4">
              <p className="text-body-md text-on-surface-variant">{t('totpBody')}</p>

              {/*
                The QR is server-supplied SVG markup. It is rendered as the
                SOURCE of an <img>, never with dangerouslySetInnerHTML: SVG
                inside an <img> executes no scripts and issues no external
                requests, so a compromised or malicious payload cannot run
                (tdd.md §6.11). Percent-encoded rather than base64 so a non-
                Latin-1 character cannot break `btoa`.
              */}
              <div className="flex justify-center">
                {/*
                  next/image is deliberately not used: this is an inline data
                  URI of fixed size, so there is nothing to fetch, resize or
                  cache. Routing it through the optimizer would add a network
                  round trip to an asset that is already in the payload.
                */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/svg+xml,${encodeURIComponent(enrollment.qr_svg)}`}
                  alt={t('qrAlt')}
                  width={192}
                  height={192}
                  className="rounded border border-outline-variant bg-surface-container-lowest p-3"
                />
              </div>

              <div className="rounded border border-outline-variant bg-surface p-4 text-center">
                <p className="text-body-sm text-on-surface-variant">{t('secretLabel')}</p>
                {/* A key the user retypes: LTR and monospaced, never reordered. */}
                <p className="force-ltr mt-1 select-all break-all font-mono text-body-md text-on-surface">
                  {enrollment.secret}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-body-md text-on-surface-variant">
                {t('emailBody', { email: enrollment.sent_to })}
              </p>
              <p className="flex items-center gap-1.5 text-body-sm text-on-surface-variant">
                {t('codeExpiresIn')}
                <CountdownReadout targetMs={otpExpiresAtMs} />
              </p>
              {/*
                Re-calling `enroll` is the only resend available: `2fa/resend`
                takes a PENDING token, which does not exist during enrolment
                (tdd.md §14.4 finding 2).
              */}
              <button
                type="button"
                onClick={() => start('email_otp', true)}
                disabled={starting !== null || resent}
                className="text-body-sm font-semibold text-primary transition-colors hover:text-primary-container disabled:cursor-not-allowed disabled:text-on-surface-variant"
              >
                {resent ? t('resent') : starting !== null ? t('resending') : t('resend')}
              </button>
            </div>
          )}

          <form onSubmit={confirm} className="space-y-6" noValidate>
            <div
              className={shaking ? 'motion-safe:animate-shake' : undefined}
              onAnimationEnd={() => setShaking(false)}
            >
              <CodeInput
                id="enroll-code"
                label={t('codeLabel')}
                value={code}
                onChange={setCode}
                length={6}
                invalid={codeError !== null}
                describedBy={codeError !== null ? 'enroll-code-error' : undefined}
                focusKey={focusKey}
                disabled={submitting}
              />
              {codeError !== null && (
                <div className="mt-2 flex justify-center">
                  <ErrorText id="enroll-code-error">{codeError}</ErrorText>
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={submitting || code.length !== 6}
              className="flex w-full items-center justify-center gap-2 rounded bg-primary-container px-4 py-4 text-label-caps uppercase tracking-wider text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? t('confirming') : t('confirm')}
              <ArrowIcon className="h-4 w-4 rtl:-scale-x-100" />
            </button>
          </form>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <div className="flex flex-col space-y-6">
        <div>
          <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
            {t('title')}
          </h1>
          <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
        </div>

        {formError && <FormBanner>{formError}</FormBanner>}

        {/*
          Both options, same component, same weight, neither preselected.
          See the note at the top of this file: this is a review gate.
        */}
        <div className="space-y-3">
          <MethodChoice
            icon={<SecurityIcon className="h-5 w-5" />}
            title={t('totpOptionTitle')}
            body={t('totpOptionBody')}
            busy={starting === 'totp'}
            onSelect={() => start('totp')}
          />
          <MethodChoice
            icon={<MailIcon className="h-5 w-5" />}
            title={t('emailOptionTitle')}
            body={t('emailOptionBody')}
            busy={starting === 'email_otp'}
            onSelect={() => start('email_otp')}
          />
        </div>

        <p className="border-t border-surface-variant pt-4 text-body-sm text-on-surface-variant">
          {t('mandatoryNote')}
        </p>
      </div>
    </AuthShell>
  )
}

function MethodChoice({
  icon,
  title,
  body,
  busy,
  onSelect,
}: {
  icon: React.ReactNode
  title: string
  body: string
  busy: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={busy}
      className="group flex w-full items-center justify-between rounded border border-outline-variant p-4 text-start transition-all hover:border-primary-container hover:bg-surface-container-low disabled:opacity-60"
    >
      <span className="flex items-center gap-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-container text-primary-container transition-colors group-hover:bg-primary-container group-hover:text-on-primary">
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
