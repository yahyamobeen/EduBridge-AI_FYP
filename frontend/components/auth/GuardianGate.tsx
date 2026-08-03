'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { AuthField } from '@/components/auth/AuthField'
import { FormBanner } from '@/components/ui/FormFeedback'
import {
  ArrowIcon,
  ChartIcon,
  CheckCircleIcon,
  LockIcon,
  MailIcon,
  ShieldIcon,
} from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { guardianInvite, guardianStatus } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { GuardianStatusResponse } from '@/lib/api/types'

/** How often the pending screen asks whether the parent has confirmed. */
const POLL_MS = 15_000

/**
 * The Class 9–10 parental gate, student side.
 *
 * THE MECHANISM IS NOT THE PROTOTYPE'S. Both supplied mockups have the student
 * type a "Guardian Space Code" that the parent generates. That was rejected in
 * v0.3.2 (decision 1): any code the student types has, by definition, passed
 * through the student, so it is not out-of-band — a student could register a
 * throwaway "parent", generate a code, and clear their own gate. That is
 * precisely the forgery this control exists to stop.
 *
 * What is kept is the prototype's STRUCTURE: the two-column card, the
 * `surface-container-high` information rail with its assurance list, the
 * `error-container` lock disc, the heading pair, and the single-field action
 * panel. Only the field changed — a parent's email address instead of a code —
 * and with it the direction of trust: the invitation goes OUT to an address the
 * student names, and the parent confirms from their own authenticated account.
 *
 * Nothing on this screen can be bypassed by skipping it. The gate is enforced
 * on every student learning endpoint at the API and RLS layers (tdd.md §3.1);
 * this is the way to satisfy it, not the thing that enforces it.
 */
export function GuardianGate() {
  const t = useTranslations('auth.guardian')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const [status, setStatus] = useState<GuardianStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [parentEmail, setParentEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const aborter = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    aborter.current?.abort()
    const controller = new AbortController()
    aborter.current = controller
    try {
      setStatus(await guardianStatus(controller.signal))
    } catch {
      // A failed poll is not worth interrupting the screen for: the next one is
      // seconds away and the visible state is still the last known truth.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Wrapped rather than called bare so the state update is unambiguously
    // asynchronous -- `refresh` only ever sets state from an awaited response.
    void (async () => {
      await refresh()
    })()
    return () => aborter.current?.abort()
  }, [refresh])

  /**
   * There is no push channel for guardian status (tdd.md §14.4 finding 5), so
   * the screen polls. It stops while the tab is hidden: a student who leaves
   * this open on a phone must not spend battery and metered data on a request
   * every fifteen seconds that nobody is there to see (prd.md A11Y-2).
   */
  const pending = status?.status === 'pending'
  useEffect(() => {
    if (!pending) return

    let timer: ReturnType<typeof setInterval> | null = null

    const start = () => {
      if (timer === null) timer = setInterval(() => void refresh(), POLL_MS)
    }
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else {
        // Catch up immediately on return rather than waiting a full interval —
        // the confirmation most likely happened while the tab was in the
        // background.
        void refresh()
        start()
      }
    }

    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [pending, refresh])

  async function invite(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})

    try {
      const result = await guardianInvite({ parent_email: parentEmail.trim() })
      setStatus({
        required: true,
        status: result.status,
        parent_email: result.parent_email,
        invited_at: new Date().toISOString(),
      })
    } catch (error) {
      if (!(error instanceof ApiError)) setFormError(te('generic'))
      else if (error.code === 'SELF_LINK_FORBIDDEN')
        setFieldErrors({ parent_email: t('selfLinkError') })
      // The parent has to sign up before they can be invited, so "no account
      // uses that address" is the most likely thing to happen on this screen.
      // Inline on the field and it reads as a next step; on the generic banner
      // it read as a fault and left the student with nothing to do.
      else if (error.code === 'GUARDIAN_NOT_FOUND')
        setFieldErrors({ parent_email: t('notFoundError') })
      else if (error.code === 'GUARDIAN_ALREADY_LINKED') void refresh()
      else if (error.code === 'VALIDATION_ERROR') setFieldErrors(error.fieldErrors())
      else if (error.code === 'RATE_LIMITED') setFormError(te('rateLimited'))
      else setFormError(te('generic'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex flex-grow items-center justify-center overflow-hidden p-gutter sm:p-margin-desktop">
      {/* Prototype backdrop: two blurred discs at 20% opacity. */}
      <div className="pointer-events-none absolute inset-0 z-0 opacity-20" aria-hidden="true">
        <div className="absolute -start-[10%] -top-[10%] h-[50%] w-[50%] rounded-full bg-primary-container blur-[120px]" />
        <div className="absolute -bottom-[10%] -end-[10%] h-[40%] w-[40%] rounded-full bg-tertiary-container blur-[100px]" />
      </div>

      <div className="relative z-10 flex w-full max-w-2xl flex-col overflow-hidden rounded-md border border-outline-variant bg-surface-container-lowest shadow-lg md:flex-row">
        {/* Information rail — 5/12, as measured in the prototype. */}
        <div className="flex w-full flex-col justify-between border-b border-outline-variant bg-surface-container-high p-8 md:w-5/12 md:border-b-0 md:border-e">
          <div>
            <span className="mb-6 block font-headline text-headline-md text-primary">
              {t('brand')}
            </span>
            <h2 className="mb-4 font-headline text-headline-lg-mobile text-on-surface md:text-headline-md">
              {t('railTitle')}
            </h2>
            <p className="mb-6 text-body-sm text-on-surface-variant">{t('railBody')}</p>
          </div>

          <ul className="space-y-4">
            <li className="flex items-start gap-3">
              <ShieldIcon className="h-5 w-5 shrink-0 text-secondary" />
              <span className="text-body-sm text-on-surface">{t('railSecure')}</span>
            </li>
            <li className="flex items-start gap-3">
              <ChartIcon className="h-5 w-5 shrink-0 text-primary" />
              <span className="text-body-sm text-on-surface">{t('railProgress')}</span>
            </li>
          </ul>
        </div>

        {/* Action panel — 7/12. */}
        <div className="flex w-full flex-col justify-center bg-surface-container-lowest p-8 md:w-7/12">
          {loading ? (
            <p role="status" className="text-body-md text-on-surface-variant">
              {t('loading')}
            </p>
          ) : status?.status === 'verified' ? (
            <div className="space-y-6 motion-safe:animate-fade-in-up">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container">
                <CheckCircleIcon className="h-6 w-6" />
              </div>
              <div>
                <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
                  {t('verifiedTitle')}
                </h1>
                <p className="text-body-md text-on-surface-variant">{t('verifiedBody')}</p>
              </div>
              <button
                type="button"
                onClick={() => router.replace('/dashboard')}
                className="flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-3 text-label-caps uppercase text-on-primary transition-colors hover:bg-surface-tint"
              >
                {t('continue')}
                <ArrowIcon className="h-[18px] w-[18px] rtl:-scale-x-100" />
              </button>
            </div>
          ) : pending ? (
            <div className="space-y-6">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-surface-container text-primary">
                <MailIcon className="h-6 w-6" />
              </div>
              <div>
                <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
                  {t('pendingTitle')}
                </h1>
                <p className="text-body-md text-on-surface-variant">
                  {t('pendingBody', { email: status?.parent_email ?? '' })}
                </p>
              </div>

              {/* The prototype's waiting pill, driven by the real poll. */}
              <div
                role="status"
                aria-live="polite"
                className="flex w-full items-center justify-center gap-3 rounded-full border border-outline-variant bg-surface-container-low px-6 py-4"
              >
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 rounded-full bg-status-pending motion-safe:animate-pulse"
                />
                <span className="text-body-md font-medium text-on-surface-variant">
                  {t('waiting')}
                </span>
              </div>

              <div className="flex flex-col gap-3 text-center">
                <button
                  type="button"
                  onClick={() => void refresh()}
                  className="text-body-sm font-semibold text-primary transition-colors hover:text-primary-container"
                >
                  {t('checkNow')}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setStatus({ ...status, status: null } as GuardianStatusResponse)
                  }
                  className="text-body-sm text-on-surface-variant transition-colors hover:text-primary"
                >
                  {t('changeEmail')}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="mb-8 text-center md:text-start">
                <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-error-container text-on-error-container">
                  <LockIcon className="h-6 w-6" />
                </div>
                <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
                  {t('title')}
                </h1>
                <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
              </div>

              <form onSubmit={invite} className="w-full space-y-6" noValidate>
                {formError && <FormBanner>{formError}</FormBanner>}

                <AuthField
                  label={t('parentEmailLabel')}
                  name="parent_email"
                  type="email"
                  autoComplete="email"
                  placeholder={t('parentEmailPlaceholder')}
                  icon={<MailIcon className="h-5 w-5" />}
                  value={parentEmail}
                  onChange={setParentEmail}
                  error={fieldErrors.parent_email}
                  required
                  disabled={submitting}
                />

                <button
                  type="submit"
                  disabled={submitting || parentEmail.trim() === ''}
                  className="flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-3 text-label-caps uppercase text-on-primary transition-colors duration-200 hover:bg-surface-tint disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? t('sending') : t('sendInvite')}
                  <ArrowIcon className="h-[18px] w-[18px] rtl:-scale-x-100" />
                </button>
              </form>

              <p className="mt-6 text-center text-body-sm text-on-surface-variant">
                {t('explainer')}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
