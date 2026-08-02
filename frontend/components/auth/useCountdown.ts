'use client'

import { useEffect, useState } from 'react'

/**
 * Seconds remaining until `targetMs`, re-rendered once a second.
 *
 * Pass `null` to stop the timer entirely — no interval is created, so a screen
 * with no active countdown does no work.
 *
 * The clock is read once when the interval starts and then on every tick, never
 * during render: reading the wall clock while rendering makes the component
 * impure, and setting state synchronously inside the effect body cascades an
 * extra render on every mount. Both are rejected by the React lint rules, and
 * both are avoidable because a countdown always MOUNTS at the moment its target
 * is set — a 423 mounts the locked panel, a 429 mounts the banner — so there is
 * no window in which the first reading could be stale.
 *
 * `null` until the first reading lands, which callers render as a placeholder
 * for a single frame.
 */
export function useCountdown(targetMs: number | null): {
  secondsLeft: number | null
  expired: boolean
} {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)

  useEffect(() => {
    if (targetMs === null) return

    const tick = () => setSecondsLeft(Math.max(0, Math.ceil((targetMs - Date.now()) / 1000)))
    // Asynchronous rather than a direct call, so the first reading is a
    // scheduled update like every later one.
    const first = setTimeout(tick, 0)
    const id = setInterval(tick, 1000)

    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [targetMs])

  if (targetMs === null) return { secondsLeft: null, expired: false }
  return { secondsLeft, expired: secondsLeft === 0 }
}

/**
 * mm:ss in Latin digits.
 *
 * Deliberately NOT localized into Urdu numerals: this reads next to one-time
 * codes and backup codes, which are Latin by definition, and it renders inside
 * `.force-ltr` so it does not reorder on an RTL page (prd.md I18N-4, the same
 * rule recorded on `.force-ltr` in globals.css).
 */
export function formatCountdown(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
