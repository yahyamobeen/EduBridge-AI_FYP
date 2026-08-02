'use client'

import { useTranslations } from 'next-intl'
import { CountdownReadout } from './Countdown'

/**
 * The locked state from the 2fa-challenge prototype, measured: a 64px
 * `error-container` disc with a small warning badge, a 24px headline, and the
 * "try again in" box on `surface` with a `surface-variant` border and a 20px
 * bold mono timer in `primary`.
 *
 * `TWO_FACTOR_LOCKED` is a 423 and carries `details.locked_until`, so the
 * countdown is driven by the SERVER's timestamp rather than by counting the
 * failures seen in this tab. The prototype counts locally and locks after three
 * attempts, which a page reload resets -- it is a demo of the visual, not the
 * rule (tdd.md §7.3).
 */
export function LockedPanel({
  lockedUntilMs,
  onExpire,
}: {
  lockedUntilMs: number | null
  onExpire?: () => void
}) {
  const t = useTranslations('auth.locked')

  return (
    <div
      role="alert"
      className="flex flex-col items-center space-y-6 py-4 text-center motion-safe:animate-fade-in-up"
    >
      <div className="relative mb-2 flex h-16 w-16 items-center justify-center rounded-full bg-error-container text-error">
        <svg viewBox="0 0 24 24" className="h-8 w-8" fill="currentColor" aria-hidden="true">
          <path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5zm-3 8V7a3 3 0 1 1 6 0v3z" />
        </svg>
        {/* -end-1, not -right-1: the badge follows the reading direction. */}
        <span className="absolute -bottom-1 -end-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-surface-container-lowest bg-surface-container-lowest">
          <svg
            viewBox="0 0 20 20"
            className="h-3.5 w-3.5 text-error"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M10 2 19 18H1zm0 5a1 1 0 0 0-1 1v4a1 1 0 1 0 2 0V8a1 1 0 0 0-1-1zm0 10.2a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4z" />
          </svg>
        </span>
      </div>

      <div>
        <h2 className="mb-2 font-headline text-headline-md text-on-surface">{t('title')}</h2>
        <p className="mb-6 text-body-md text-on-surface-variant">{t('body')}</p>
      </div>

      {lockedUntilMs !== null && (
        <div className="flex w-full flex-col items-center justify-center gap-2 rounded border border-surface-variant bg-surface p-4">
          <span className="text-body-sm text-on-surface-variant">{t('tryAgainIn')}</span>
          <CountdownReadout
            targetMs={lockedUntilMs}
            {...(onExpire ? { onExpire } : {})}
            className="text-xl font-bold text-primary"
          />
        </div>
      )}
    </div>
  )
}
