'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthPanel, AuthShell } from '@/components/auth/AuthShell'
import { FormBanner } from '@/components/ui/FormFeedback'
import { MailOpenIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { resendVerification } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import { getUnverifiedEmail } from '@/lib/auth/challenge'

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

  async function resend() {
    if (email === null || email === '') return
    setState('sending')
    setError(null)
    try {
      await resendVerification({ email })
      setState('sent')
    } catch (caught) {
      setState('failed')
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
            <button
              type="button"
              onClick={resend}
              disabled={state === 'sending' || state === 'sent'}
              className="w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
            >
              {state === 'sent'
                ? t('resent')
                : state === 'sending'
                  ? t('resending')
                  : t('resend')}
            </button>
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
