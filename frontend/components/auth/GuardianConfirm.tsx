'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { AlertCircleIcon, ArrowIcon, CheckCircleIcon, UsersIcon } from '@/components/ui/Icon'
import { Link, useRouter } from '@/i18n/navigation'
import { guardianConfirm } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'

type State = 'ready' | 'confirmed' | 'invalid' | 'already'

/**
 * The parent's side of the gate.
 *
 * The prototype generates a "space code" for the parent to read out to their
 * child. That direction is retired (decision 1) — a code the student types is
 * not out-of-band. Here the parent arrives from the invitation in their own
 * mailbox and confirms from their own authenticated account, which is what
 * makes the signal one the student cannot manufacture.
 *
 * The prototype's SHELL is kept: the header block with its icon and heading
 * pair, the numbered explanation of what happens, and the footer action bar.
 * The numbered list changed from "how to generate a code" to what confirming
 * actually does and does not grant — a parent about to authorise access to
 * their child's account deserves to be told that they will see progress and
 * will NOT see tutoring conversations (`prd.md` §4.2).
 *
 * `guardian/confirm` is authenticated as the parent (v0.3.2), so an unsigned-in
 * visitor is sent to sign-up first; the client cannot confirm on their behalf.
 */
export function GuardianConfirm({
  token,
  signedIn,
}: {
  token: string | null
  signedIn: boolean
}) {
  const t = useTranslations('auth.guardianConfirm')
  const te = useTranslations('auth.errors')
  const router = useRouter()

  const [state, setState] = useState<State>(token === null ? 'invalid' : 'ready')
  // Nullable because `app_user.full_name` is. A confirmation is not worth
  // failing over a missing name — the copy just stops naming the child.
  const [studentName, setStudentName] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  async function confirm() {
    if (token === null) return
    setSubmitting(true)
    setFormError(null)
    try {
      const result = await guardianConfirm({ invite_token: token })
      setStudentName(result.student_name)
      setState('confirmed')
    } catch (error) {
      setSubmitting(false)
      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
        return
      }
      if (error.code === 'GUARDIAN_ALREADY_LINKED') setState('already')
      else if (error.code === 'INVALID_TOKEN' || error.code === 'TOKEN_EXPIRED')
        setState('invalid')
      else if (error.code === 'SELF_LINK_FORBIDDEN') setFormError(t('selfLinkError'))
      else if (error.code === 'FORBIDDEN_SCOPE') setFormError(t('notAParentError'))
      else setFormError(te('generic'))
    }
  }

  const steps = ['step1', 'step2', 'step3'] as const

  return (
    <div className="flex flex-grow items-center justify-center p-margin-mobile md:p-margin-desktop">
      <main className="relative flex w-full max-w-2xl flex-col overflow-hidden rounded-md border border-outline-variant bg-surface-container-lowest shadow-sm">
        <div className="border-b border-outline-variant bg-surface-container px-8 py-8 text-center">
          <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary-container text-on-primary">
            {state === 'confirmed' ? (
              <CheckCircleIcon className="h-6 w-6" />
            ) : state === 'invalid' ? (
              <AlertCircleIcon className="h-6 w-6" />
            ) : (
              <UsersIcon className="h-6 w-6" />
            )}
          </div>
          <h1 className="mb-2 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
            {state === 'confirmed'
              ? t('confirmedTitle')
              : state === 'already'
                ? t('alreadyTitle')
                : state === 'invalid'
                  ? t('invalidTitle')
                  : t('title')}
          </h1>
          <p className="text-body-md text-on-surface-variant">
            {state === 'confirmed'
              ? studentName
                ? t('confirmedBody', { student: studentName })
                : t('confirmedBodyNoName')
              : state === 'already'
                ? t('alreadyBody')
                : state === 'invalid'
                  ? t('invalidBody')
                  : t('subtitle')}
          </p>
        </div>

        <div className="flex flex-col items-center p-8">
          {formError && (
            <div className="mb-6 w-full">
              <FormBanner>{formError}</FormBanner>
            </div>
          )}

          {state === 'ready' && (
            <ol className="mb-10 w-full max-w-md space-y-4">
              {steps.map((step, index) => (
                <li key={step} className="flex items-start gap-4">
                  <span
                    aria-hidden="true"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-container font-headline text-body-sm text-on-primary-container"
                  >
                    {index + 1}
                  </span>
                  <span className="mt-1 text-body-md text-on-surface">{t(step)}</span>
                </li>
              ))}
            </ol>
          )}

          {state === 'ready' && !signedIn && (
            <div className="w-full max-w-md space-y-3 text-center">
              <p className="text-body-sm text-on-surface-variant">{t('signInFirst')}</p>
              <Link
                href="/signup/parent"
                className="block w-full rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary transition-colors hover:bg-primary-container"
              >
                {t('createParentAccount')}
              </Link>
              <Link
                href="/login"
                className="block text-body-sm text-primary transition-colors hover:text-primary-container"
              >
                {t('haveAccount')}
              </Link>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-outline-variant bg-surface-container-highest p-6">
          <Link
            href="/coming-soon/help"
            className="text-body-sm text-on-surface-variant transition-colors hover:text-primary"
          >
            {t('needHelp')}
          </Link>

          {state === 'confirmed' || state === 'already' ? (
            <button
              type="button"
              onClick={() => router.replace('/parent')}
              className="rounded bg-primary px-6 py-2.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-fixed-dim"
            >
              {t('continue')}
            </button>
          ) : (
            <button
              type="button"
              onClick={confirm}
              disabled={!signedIn || submitting || state === 'invalid'}
              className="flex items-center gap-2 rounded bg-primary px-6 py-2.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-fixed-dim disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? t('confirming') : t('confirm')}
              <ArrowIcon className="h-[18px] w-[18px] rtl:-scale-x-100" />
            </button>
          )}
        </div>
      </main>
    </div>
  )
}
