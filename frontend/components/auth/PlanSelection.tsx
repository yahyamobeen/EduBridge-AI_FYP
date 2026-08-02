'use client'

import { useEffect, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { AuthFooterLinks } from '@/components/auth/AuthFooterLinks'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowIcon, CheckCircleIcon, SecurityIcon } from '@/components/ui/Icon'
import { useRouter } from '@/i18n/navigation'
import { apiFetch } from '@/lib/api/client'
import { ApiError } from '@/lib/api/errors'
import type { SubscriptionResponse } from '@/lib/api/types'

const FEATURES = ['tutor', 'curriculum', 'analytics', 'languages'] as const

/**
 * Plan selection, after the guardian gate and whenever a trial lapses.
 *
 * THE PROTOTYPE IS SUPERSEDED HERE, on price and on shape. It offers a free
 * Basic tier beside a Rs. 1,500 Pro tier and a full card/EasyPaisa checkout.
 * The product has ONE tier at Rs. 999/month with a 14-day trial and NO free
 * tier (prd.md §2.6, decisions 2 and 3), and Card 1 builds the plan screen
 * WITHOUT checkout (decision 14) — no payment provider is chosen, and Stripe
 * does not support Pakistani acquiring (assumption A7). Its structure is kept:
 * the transactional header, the centred heading pair, the gradient plan card
 * and the feature list with check marks.
 *
 * A free tier could not be shown even as a courtesy: with no free tier, access
 * genuinely ends when the trial does, and a screen implying otherwise would be
 * a promise the product does not keep.
 */
export function PlanSelection() {
  const t = useTranslations('plan')
  const te = useTranslations('auth.errors')
  const format = useFormatter()
  const router = useRouter()

  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const result = await apiFetch<SubscriptionResponse>('/subscription')
        if (!cancelled) setSubscription(result)
      } catch (caught) {
        // A missing subscription record FAILS CLOSED (prd.md MON-2): it means
        // no access, never an implied trial. The screen still renders the plan,
        // which is the action that fixes it.
        if (
          !cancelled &&
          caught instanceof ApiError &&
          caught.code !== 'SUBSCRIPTION_REQUIRED'
        ) {
          setError(te('generic'))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [te])

  async function select() {
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch('/subscription/select', { method: 'POST', body: { plan: 'standard' } })
      router.replace('/dashboard')
    } catch (caught) {
      setSubmitting(false)
      setError(
        caught instanceof ApiError && caught.code === 'RATE_LIMITED'
          ? te('rateLimited')
          : te('generic'),
      )
    }
  }

  const trialEndsAt = subscription?.trial_ends_at
  const onTrial = subscription?.status === 'trialing' && trialEndsAt !== null
  /*
    Rendered from the UTC instant the server sent, formatted in the reader's
    zone. Deliberately not computed as a day count in the browser: Pakistan is
    UTC+5, so "expires today" straddles a date boundary and a local date
    subtraction is off by one for part of every day (assumption A8).
  */
  const trialEnds = trialEndsAt ? new Date(trialEndsAt) : null

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 flex w-full items-center justify-between border-b border-outline-variant bg-surface-container-lowest px-6 py-4">
        <div className="flex items-center gap-3">
          <SecurityIcon className="h-6 w-6 text-primary" />
          <span className="font-headline text-headline-md font-bold text-primary">
            {t('brand')}
          </span>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-container-max flex-grow flex-col items-center justify-center p-margin-mobile md:p-margin-desktop">
        <div className="mb-12 max-w-2xl text-center">
          <h1 className="mb-4 font-headline text-headline-lg-mobile text-on-surface md:text-headline-lg">
            {t('title')}
          </h1>
          <p className="text-body-lg text-on-surface-variant">{t('subtitle')}</p>
        </div>

        {error !== null && (
          <div className="mb-6 w-full max-w-3xl">
            <FormBanner>{error}</FormBanner>
          </div>
        )}

        <div className="grid w-full max-w-3xl grid-cols-1 gap-gutter lg:grid-cols-12">
          {/* The prototype's gradient card, now carrying the only real tier. */}
          <div className="relative flex flex-col overflow-hidden rounded-md bg-gradient-to-br from-primary to-primary-container p-6 text-on-primary shadow-xl lg:col-span-7">
            <div className="mb-6 border-b border-primary-fixed-dim/30 pb-6">
              <h2 className="mb-2 font-headline text-headline-md text-on-primary">
                {t('planName')}
              </h2>
              <p className="flex items-baseline gap-1">
                <span className="font-headline text-headline-lg text-on-primary">
                  {t('price')}
                </span>
                <span className="text-body-sm text-primary-fixed-dim">{t('perMonth')}</span>
              </p>
              <p className="mt-2 text-body-sm text-primary-fixed-dim">{t('planBody')}</p>
            </div>

            <ul className="mb-8 flex-grow space-y-4">
              {FEATURES.map((feature) => (
                <li key={feature} className="flex items-start gap-3">
                  <CheckCircleIcon className="mt-0.5 h-5 w-5 shrink-0 text-secondary-fixed" />
                  <span className="text-body-md text-on-primary">
                    {t(`feature_${feature}`)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-col rounded-md border border-outline-variant bg-surface-container-lowest p-6 shadow-sm lg:col-span-5">
            <h3 className="font-headline text-headline-md text-on-surface">
              {t('statusTitle')}
            </h3>

            <div className="mt-4 flex-grow">
              {loading ? (
                <p role="status" className="text-body-sm text-on-surface-variant">
                  {t('loading')}
                </p>
              ) : onTrial && trialEnds !== null ? (
                <p className="text-body-md text-on-surface-variant">
                  {t('trialEnds', {
                    date: format.dateTime(trialEnds, {
                      dateStyle: 'long',
                      timeStyle: 'short',
                    }),
                  })}
                </p>
              ) : (
                <p className="text-body-md text-on-surface-variant">{t('noAccess')}</p>
              )}
            </div>

            <button
              type="button"
              onClick={select}
              disabled={submitting}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded bg-primary px-4 py-3 text-label-caps uppercase text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? t('selecting') : t('select')}
              <ArrowIcon className="h-[18px] w-[18px] rtl:-scale-x-100" />
            </button>

            {/*
              Said plainly rather than hidden: no payment is taken on this
              screen, because no provider is chosen yet (assumption A7).
            */}
            <p className="mt-4 text-body-sm text-on-surface-variant">{t('noCheckoutNote')}</p>
          </div>
        </div>

        <AuthFooterLinks />
      </main>
    </div>
  )
}
