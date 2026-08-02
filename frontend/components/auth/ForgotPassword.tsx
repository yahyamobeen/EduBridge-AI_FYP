'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthField } from '@/components/auth/AuthField'
import { AuthPanel, AuthShell } from '@/components/auth/AuthShell'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowLeftIcon, MailIcon, MailOpenIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { forgotPassword } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'

/**
 * Begin a password reset.
 *
 * THE RULE THAT SHAPES THIS SCREEN: the response is identical whether or not
 * the address exists (tdd.md §3.1), and the UI must be too. "No account with
 * that email" would turn this form into an account-enumeration oracle that
 * anyone can query without signing in — so the confirmation panel is shown for
 * every accepted submission, and the address is echoed back exactly as typed
 * rather than as anything the server confirmed.
 *
 * `429` is the one exception, because rate limiting is about this browser's
 * behaviour and leaks nothing about which addresses are registered.
 */
export function ForgotPassword() {
  const t = useTranslations('auth.forgotPassword')
  const te = useTranslations('auth.errors')

  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})

    try {
      await forgotPassword({ email: email.trim() })
      setSentTo(email.trim())
    } catch (error) {
      if (error instanceof ApiError && error.code === 'VALIDATION_ERROR') {
        setFieldErrors(error.fieldErrors())
      } else if (error instanceof ApiError && error.code === 'RATE_LIMITED') {
        setFormError(te('rateLimited'))
      } else {
        setFormError(te('generic'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (sentTo !== null) {
    return (
      <AuthShell>
        <AuthPanel
          icon={<MailOpenIcon className="h-8 w-8" />}
          title={t('sentTitle')}
          body={t('sentBody', { email: sentTo })}
        >
          <div className="w-full space-y-4">
            <p className="text-body-sm text-on-surface-variant">{t('spamHint')}</p>
            <button
              type="button"
              onClick={() => setSentTo(null)}
              className="text-body-sm font-semibold text-primary transition-colors hover:text-primary-container"
            >
              {t('tryAnotherAddress')}
            </button>
          </div>
        </AuthPanel>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <div className="space-y-6">
        <div>
          <h1 className="mb-2 font-headline text-headline-md text-on-surface">{t('title')}</h1>
          <p className="text-body-sm text-on-surface-variant">{t('subtitle')}</p>
        </div>

        <form onSubmit={submit} className="space-y-6" noValidate>
          {formError && <FormBanner>{formError}</FormBanner>}

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

          <button
            type="submit"
            disabled={submitting || email.trim() === ''}
            className="w-full rounded bg-primary px-4 py-3 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-container hover:text-on-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t('sending') : t('submit')}
          </button>
        </form>

        <div className="text-center">
          <Link
            href="/login"
            className="inline-flex items-center gap-2 text-body-sm text-primary transition-colors hover:text-primary-container"
          >
            <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
            {t('backToLogin')}
          </Link>
        </div>
      </div>
    </AuthShell>
  )
}
