'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthPanel, AuthShell } from '@/components/auth/AuthShell'
import { useCountdown } from '@/components/auth/useCountdown'
import { FormBanner } from '@/components/ui/FormFeedback'
import { MailOpenIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { resendVerification } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import { getUnverifiedEmail } from '@/lib/auth/challenge'

/**
 * How long the resend button stays disabled after a send.
 *
 * Mail is not instant, and a button that can be pressed again immediately gets
 * pressed again immediately — which mostly produces duplicate mail and burns
 * the server's per-address budget (`EMAIL_RESEND_LIMIT`) before the first one
 * has landed. A minute is long enough for delivery on a slow provider and short
 * enough not to feel like a punishment.
 */
const RESEND_COOLDOWN_MS = 60_000

/**
 * When the button becomes pressable again.
 *
 * Module scope, not inline: the clock is impure, and the React lint rules
 * reject reading it anywhere they cannot prove is outside render. This is only
 * ever called from the click handler.
 */
function cooldownTarget(): number {
  return Date.now() + RESEND_COOLDOWN_MS
}

/** Display-only masking; the address came from this browser. */
function maskEmail(email: string): string {
  const [name = '', domain = ''] = email.split('@')
  return `${name.slice(0, 1)}${'*'.repeat(Math.max(2, name.length - 1))}@${domain}`
}

/**
 * Where registration and an unverified sign-in both land.
 *
 * The address shown is the one the user typed, kept in memory by whichever
 * screen sent them here: `status: 'email_verification_required'` returns a
 * MASKED address, which `/auth/email/resend` cannot act on (tdd.md §3.1).
 *
 * If it is missing — a direct visit, or a reload — the screen says so and
 * offers sign-in rather than showing a resend button that cannot work.
 */
export function CheckEmail() {
  const t = useTranslations('auth.checkEmail')
  const te = useTranslations('auth.errors')

  const email = getUnverifiedEmail()
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null)

  // Counts down only while a cooldown is running; `null` creates no interval.
  const { secondsLeft, expired } = useCountdown(cooldownUntil)
  const cooling = cooldownUntil !== null && !expired

  async function resend() {
    if (email === null || email === '') return
    setState('sending')
    setError(null)
    try {
      await resendVerification({ email })
      setState('sent')
      setCooldownUntil(cooldownTarget())
    } catch (caught) {
      setState('failed')
      // NO cooldown on failure. Nothing was sent, so making the user wait a
      // minute before retrying would punish them for the server's problem.
      setError(
        caught instanceof ApiError && caught.code === 'RATE_LIMITED'
          ? te('rateLimited')
          : te('generic'),
      )
    }
  }

  return (
    <AuthShell>
      <AuthPanel
        icon={<MailOpenIcon className="h-8 w-8" />}
        title={t('title')}
        body={email ? t('body', { email: maskEmail(email) }) : t('bodyUnknown')}
      >
        <div className="w-full space-y-4">
          {error !== null && <FormBanner>{error}</FormBanner>}

          <p className="text-body-sm text-on-surface-variant">{t('spamHint')}</p>

          {email ? (
            <>
              <button
                type="button"
                onClick={resend}
                disabled={state === 'sending' || cooling}
                className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
              >
                {state === 'sending'
                  ? t('resending')
                  : cooling
                    ? // `secondsLeft` is null for the first frame, before the
                      // timer's first reading lands.
                      t('resendIn', { seconds: secondsLeft ?? RESEND_COOLDOWN_MS / 1000 })
                    : t('resend')}
              </button>

              {/* Announced politely rather than assertively: it is a
                  confirmation, not something that should interrupt whatever a
                  screen reader is already saying (prd.md A11Y-1). */}
              {state === 'sent' && (
                <p role="status" aria-live="polite" className="text-body-sm text-secondary">
                  {t('resent')}
                </p>
              )}
            </>
          ) : null}

          <Link
            href="/login"
            className="block w-full text-body-sm text-primary transition-colors hover:text-primary-container"
          >
            {t('backToSignIn')}
          </Link>
        </div>
      </AuthPanel>
    </AuthShell>
  )
}
