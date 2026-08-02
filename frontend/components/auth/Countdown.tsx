'use client'

import { useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { formatCountdown, useCountdown } from './useCountdown'

/**
 * A ticking mm:ss readout that is also announced, without being unbearable.
 *
 * prd.md A11Y-1 requires countdowns to be announced rather than ticking
 * silently. Putting `aria-live` on the seconds themselves would satisfy the
 * letter of that and defeat its purpose: a polite region that changes once a
 * second interrupts a screen-reader user continuously for the whole lockout.
 *
 * So the visible readout ticks silently and a separate live region announces a
 * coarse "about N minutes left", changing only when the minute changes. Sighted
 * users get the precise timer; assistive-technology users get the information
 * without the noise.
 */
export function CountdownReadout({
  targetMs,
  onExpire,
  className,
}: {
  targetMs: number | null
  onExpire?: () => void
  className?: string
}) {
  const t = useTranslations('auth.countdown')
  const { secondsLeft, expired } = useCountdown(targetMs)

  // In an effect, not during render: calling back into a parent's setState from
  // a render pass is the "cannot update a component while rendering another"
  // warning, and in a loop it would not settle.
  useEffect(() => {
    if (expired && onExpire) onExpire()
  }, [expired, onExpire])

  return (
    <>
      <span aria-hidden="true" className={`force-ltr font-mono ${className ?? ''}`}>
        {/* One frame of placeholder before the first reading, rather than a
            wall-clock read during render. Same width, so nothing shifts. */}
        {secondsLeft === null ? '--:--' : formatCountdown(secondsLeft)}
      </span>
      <span aria-live="polite" className="sr-only">
        {secondsLeft === null
          ? ''
          : secondsLeft === 0
            ? t('finished')
            : secondsLeft < 60
              ? t('lessThanAMinute')
              : t('minutesLeft', { minutes: Math.ceil(secondsLeft / 60) })}
      </span>
    </>
  )
}
