'use client'

import type { ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { AuthFooterLinks } from '@/components/auth/AuthFooterLinks'
import { SecurityIcon } from '@/components/ui/Icon'

/**
 * The centred card layout from the 2fa-challenge prototype, measured: a 448px
 * column, a 40px `primary-container` logo tile beside the 24px wordmark, and a
 * 32px-padded card with a 12px radius on `outline-variant`.
 *
 * Extracted because every remaining transactional screen — enrolment, email
 * verification, password reset, the parental gate — is the same shape. There is
 * no prototype for several of them, so reusing this one is what keeps them from
 * each inventing their own.
 *
 * The backdrop is the prototype's three blurred discs, at the measured 80/100/
 * 60px blurs. They sit behind `pointer-events-none` and are hidden from
 * assistive technology.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  const t = useTranslations('auth.twoFactor')

  return (
    <div className="relative flex flex-grow items-center justify-center overflow-hidden p-margin-mobile md:p-margin-desktop">
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
          {children}
        </div>

        <AuthFooterLinks />
      </div>
    </div>
  )
}

/** The icon-disc + heading + body block the panels share. */
export function AuthPanel({
  tone = 'neutral',
  icon,
  title,
  body,
  children,
}: {
  tone?: 'neutral' | 'error' | 'success'
  icon: ReactNode
  title: string
  body: string
  children?: ReactNode
}) {
  const disc = {
    neutral: 'bg-surface-container text-on-surface-variant',
    error: 'bg-error-container text-error',
    success: 'bg-secondary-container text-on-secondary-container',
  }[tone]

  return (
    <div
      role={tone === 'error' ? 'alert' : undefined}
      className="flex flex-col items-center space-y-6 py-4 text-center motion-safe:animate-fade-in-up"
    >
      <div className={`flex h-16 w-16 items-center justify-center rounded-full ${disc}`}>
        {icon}
      </div>
      <div>
        <h1 className="mb-2 font-headline text-headline-md text-on-surface">{title}</h1>
        <p className="text-body-md text-on-surface-variant">{body}</p>
      </div>
      {children}
    </div>
  )
}
