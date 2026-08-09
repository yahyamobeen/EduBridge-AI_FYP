'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { register as registerAccount } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import { useRouter } from '@/i18n/navigation'
import { FormBanner } from '@/components/ui/FormFeedback'
import { Turnstile } from '@/components/auth/Turnstile'
import { TextField } from './fields'

/**
 * Teacher and parent registration.
 *
 * The teacher prototype also had institution, specialization and a credential
 * upload. Those are not built: no endpoint accepts them and prd.md has no
 * educator-verification requirement, so they would be controls that discard
 * whatever the user typed. The prototype's structure and motion are kept.
 */
export function SimpleSignupForm({ role }: { role: 'teacher' | 'parent' }) {
  const t = useTranslations(`signup.${role}`)
  const tc = useTranslations('signup.common')
  const te = useTranslations('signup.errors')
  const locale = useLocale()
  const router = useRouter()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaNonce, setCaptchaNonce] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const mismatch = confirmPassword !== '' && confirmPassword !== password
  const complete =
    fullName.trim() !== '' &&
    email.trim() !== '' &&
    password.length >= 8 &&
    confirmPassword === password &&
    confirmPassword !== '' &&
    captchaToken !== null

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})
    try {
      await registerAccount({
        email,
        password,
        full_name: fullName,
        role,
        turnstile_token: captchaToken ?? '',
      })
      router.push('/onboarding/email')
    } catch (error) {
      // Any failed submit means siteverify consumed the token. Drop it and
      // force a fresh solve; never re-enable submit with a dead token.
      setCaptchaToken(null)
      setCaptchaNonce((n) => n + 1)
      if (!(error instanceof ApiError)) setFormError(te('generic'))
      else if (error.code === 'EMAIL_ALREADY_REGISTERED')
        setFieldErrors({ email: te('emailTaken') })
      else if (error.code === 'VALIDATION_ERROR') setFieldErrors(error.fieldErrors())
      else if (error.code === 'CAPTCHA_FAILED') setFormError(te('captchaFailed'))
      else if (error.code === 'RATE_LIMITED') setFormError(te('rateLimited'))
      else setFormError(te('generic'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] w-full flex-col md:flex-row">
      <aside className="hidden w-2/5 flex-col justify-between overflow-hidden bg-primary-container p-12 text-on-primary-container md:flex">
        <div>
          <p className="font-headline text-headline-lg font-bold">EduBridge AI</p>
          <p className="mt-3 max-w-md text-body-lg opacity-90">{t('subtitle')}</p>
        </div>
      </aside>

      <div className="flex flex-1 items-center justify-center bg-surface px-gutter py-12">
        <form onSubmit={submit} className="w-full max-w-xl motion-safe:animate-roll-down">
          <h1 className="font-headline text-headline-lg text-on-primary-fixed">{t('title')}</h1>
          <p className="mt-2 text-body-md text-on-surface-variant">{t('subtitle')}</p>

          <div className="mt-8 space-y-5">
            {formError && <FormBanner>{formError}</FormBanner>}
            <TextField
              label={tc('fullName')}
              name="full_name"
              autoComplete="name"
              required
              error={fieldErrors.full_name}
              register={{
                value: fullName,
                onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                  setFullName(e.target.value),
              }}
            />
            <TextField
              label={tc('email')}
              name="email"
              type="email"
              autoComplete="username"
              required
              error={fieldErrors.email}
              register={{
                value: email,
                onChange: (e: React.ChangeEvent<HTMLInputElement>) => setEmail(e.target.value),
              }}
            />
            <TextField
              label={tc('password')}
              name="password"
              type="password"
              autoComplete="new-password"
              hint={tc('passwordHint')}
              required
              error={fieldErrors.password}
              register={{
                value: password,
                onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                  setPassword(e.target.value),
              }}
            />
            <TextField
              label={tc('confirmPassword')}
              name="confirm_password"
              type="password"
              autoComplete="new-password"
              hint={tc('confirmPasswordHint')}
              required
              error={mismatch ? tc('mismatch') : fieldErrors.confirm_password}
              register={{
                value: confirmPassword,
                onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                  setConfirmPassword(e.target.value),
              }}
            />
            <div>
              <p className="mb-1 text-body-sm text-on-surface-variant">
                {tc('turnstileLabel')}
              </p>
              <Turnstile
                onVerify={setCaptchaToken}
                onExpired={() => setCaptchaToken(null)}
                resetNonce={captchaNonce}
              />
            </div>
          </div>

          <div className="mt-10 flex items-center justify-between gap-4">
            <p className="text-body-sm text-on-surface-variant">
              {tc('haveAccount')}{' '}
              <a href={`/${locale}/login`} className="font-semibold text-primary underline">
                {tc('signIn')}
              </a>
            </p>
            <button
              type="submit"
              disabled={submitting || !complete}
              className="rounded bg-primary-container px-6 py-3 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? tc('submitting') : tc('submit')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
