'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthPanel, AuthShell } from '@/components/auth/AuthShell'
import { FormBanner } from '@/components/ui/FormFeedback'
import { AlertCircleIcon, CheckCircleIcon, HistoryIcon } from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { resendVerification, startSession, verifyEmail } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { EmailVerifyResponse } from '@/lib/api/types'
import {
  getUnverifiedEmail,
  setEnrollmentHandoff,
  setUnverifiedEmail,
} from '@/lib/auth/challenge'
import { pendingOnboardingRoute } from '@/lib/auth/onboarding'

type State = 'verifying' | 'verified' | 'invalid' | 'expired' | 'missing'

/**
 * The verification link's landing page.
 *
 * The prototype has three panels — success, invalid, expired — switched by
 * developer buttons. A fourth is required in a real implementation: **verifying**.
 * The token has to be exchanged with the server before any of the other three
 * can be known, and on a slow connection that is seconds of blank card unless
 * the wait is designed.
 *
 * A verification link is commonly requested TWICE — a mail client prefetches it,
 * then the human clicks — so the exchange is guarded against firing twice from
 * one mount, which in React's development StrictMode it otherwise would.
 */
export function VerifyEmail({ token }: { token: string | null }) {
  const t = useTranslations('auth.verifyEmail')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const [state, setState] = useState<State>(token === null ? 'missing' : 'verifying')
  const [next, setNext] = useState<string | null>(null)
  const [resendState, setResendState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')
  // ⚠️ FINDING D5 — THE IN-FLIGHT REQUEST, NOT A `hasAttempted` BOOLEAN.
  //
  // This used to be `useRef(false)` with an early return, which is precisely
  // the shape `SessionGuard` records as deadlocking in development:
  // `reactStrictMode` mounts, unmounts and remounts; the unmount sets
  // `cancelled` and discards the in-flight response, the remount finds the ref
  // still `true` — refs survive the double-invoke — and returns early. The first
  // result is thrown away, the second request is never made, and the screen sits
  // on "Verifying…" for ever with a healthy 200 in the network tab. Development
  // only, so nothing in CI could see it.
  //
  // ⚠️ DELETING THE GUARD WOULD BE WORSE, WHICH IS WHY THE REF STAYS. The
  //    verification token is SINGLE-USE and mail clients prefetch links, so a
  //    second request consumes it and answers INVALID_TOKEN — turning "your
  //    email is verified" into "this link is invalid" for a user who did nothing
  //    wrong.
  //
  // Holding the PROMISE satisfies both: exactly one request is ever issued, and
  // a remount subscribes to that same request instead of starting another or
  // giving up. If it has already settled, `.then` still fires.
  const inFlight = useRef<Promise<EmailVerifyResponse> | null>(null)

  useEffect(() => {
    if (token === null) return

    if (inFlight.current === null) {
      const started = verifyEmail({ token })
      // The real handler is attached on every mount below. This one only stops
      // a rejection that lands during StrictMode's unmounted gap from surfacing
      // as an unhandled promise rejection.
      started.catch(() => {})
      inFlight.current = started
    }
    // Held in a local so it is `Promise<EmailVerifyResponse>` rather than
    // `... | null` at the await; the ref is nullable, this is not.
    const request = inFlight.current

    let cancelled = false
    void (async () => {
      try {
        const result = await request
        if (cancelled) return

        // The token this returns is scoped to onboarding routes only; it is not
        // a full session (tdd.md §3.1). Enrolment is what turns it into one.
        startSession(result.access_token, result.expires_in)
        setEnrollmentHandoff({
          token: result.enrollment_token,
          expiresAtMs: Date.now() + result.expires_in * 1000,
          email: getUnverifiedEmail() ?? '',
        })
        setNext(pendingOnboardingRoute(result.onboarding_state) ?? '/dashboard')
        setState('verified')
      } catch (error) {
        if (cancelled) return
        if (error instanceof ApiError && error.code === 'TOKEN_EXPIRED') setState('expired')
        else setState('invalid')
      }
    })()

    return () => {
      cancelled = true
    }
  }, [token])

  async function resend() {
    const email = getUnverifiedEmail()
    // Without the address there is nothing to resend to. The verification link
    // does not carry it, and the API needs a real address -- so the honest
    // answer is to send the user back to sign in, which produces one.
    if (email === null || email === '') {
      router.push('/login')
      return
    }
    setResendState('sending')
    try {
      await resendVerification({ email })
      setResendState('sent')
    } catch {
      setResendState('failed')
    }
  }

  if (state === 'verifying') {
    return (
      <AuthShell>
        <div
          role="status"
          className="flex flex-col items-center space-y-6 py-4 text-center"
          aria-live="polite"
        >
          <span
            aria-hidden="true"
            className="h-16 w-16 rounded-full border-4 border-surface-variant border-t-primary motion-safe:animate-spin"
          />
          <div>
            <h1 className="mb-2 font-headline text-headline-md text-on-surface">
              {t('verifyingTitle')}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('verifyingBody')}</p>
          </div>
        </div>
      </AuthShell>
    )
  }

  if (state === 'verified') {
    return (
      <AuthShell>
        <AuthPanel
          tone="success"
          icon={<CheckCircleIcon className="h-8 w-8" />}
          title={t('verifiedTitle')}
          body={t('verifiedBody')}
        >
          <button
            type="button"
            onClick={() => router.replace(next ?? '/dashboard')}
            className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container"
          >
            {t('continue')}
          </button>
        </AuthPanel>
      </AuthShell>
    )
  }

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
        <div className="w-full space-y-4">
          {resendState === 'failed' && <FormBanner>{te('generic')}</FormBanner>}
          <button
            type="button"
            onClick={resend}
            disabled={resendState === 'sending' || resendState === 'sent'}
            className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            {resendState === 'sent' ? t('resent') : t('resend')}
          </button>
          <button
            type="button"
            onClick={() => {
              setUnverifiedEmail('')
              router.push('/login')
            }}
            className="w-full text-body-sm text-primary transition-colors hover:text-primary-container"
          >
            {t('backToSignIn')}
          </button>
        </div>
      </AuthPanel>
    </AuthShell>
  )
}
