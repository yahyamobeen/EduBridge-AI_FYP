'use client'

import { useEffect, useRef } from 'react'
import { useLocale } from 'next-intl'

/**
 * Cloudflare Turnstile widget, hand-rolled (no wrapper package) — see
 * docs/plans/captchaPLAN.md §4.3 for the dependency decision.
 *
 * Lifecycle contract (the rules the forms depend on):
 * - the challenge script is loaded ONCE, on the first render of this
 *   component, and the widget is rendered explicitly into a container ref;
 * - `onVerify(token)` fires for every FRESH token. Tokens are single-use and
 *   short-lived, so a token that did not come from the latest verify is stale;
 * - `resetNonce`: bumping the value imperatively resets the widget. Every
 *   form does this on a failed submit, because the siteverify call consumed
 *   the token and the widget must not re-arm itself with it;
 * - `onExpired` fires when an outstanding token lapses mid-session; the host
 *   must stop considering the token submittable.
 *
 * The host page's CSP must admit challenges.cloudflare.com in script-src,
 * frame-src and connect-src — this widget runs inside a Cloudflare-served
 * iframe that fetches from that origin (next.config.mjs, "Turnstile" block).
 */

type TurnstileApi = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string
  reset: (widgetId: string) => void
  remove: (widgetId: string) => void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

/** The script is loaded once per session; later mounts reuse the pending promise. */
let apiPromise: Promise<TurnstileApi> | null = null

function loadTurnstileApi(): Promise<TurnstileApi> {
  if (apiPromise) return apiPromise
  apiPromise = new Promise((resolve) => {
    if (window.turnstile) {
      resolve(window.turnstile)
      return
    }
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-edubridge-turnstile]',
    )
    const script =
      existing ??
      (() => {
        const el = document.createElement('script')
        el.src = SCRIPT_URL
        el.async = true
        el.dataset.edubridgeTurnstile = 'true'
        document.head.appendChild(el)
        return el
      })()
    script.addEventListener('load', () => resolve(window.turnstile!), { once: true })
  })
  return apiPromise
}

type Props = {
  onVerify: (token: string) => void
  onExpired?: () => void
  /** Bumping this value imperatively resets the widget (see forms). */
  resetNonce?: number
  className?: string
}

export function Turnstile({ onVerify, onExpired, resetNonce = 0, className }: Props) {
  const locale = useLocale()
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetIdRef = useRef<string | null>(null)

  // PUBLIC site key by design (NEXT_PUBLIC_ prefix); the SECRET key lives
  // only in backend/.env and never has this prefix (captchaPLAN.md §B1).
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? ''

  // The callbacks and locale are read through refs so the widget is created
  // exactly once per siteKey and never re-rendered on parent re-renders —
  // recreating the widget mid-session would discard a solve in progress.
  const onVerifyRef = useRef(onVerify)
  const onExpiredRef = useRef(onExpired)
  const localeRef = useRef(locale)
  useEffect(() => {
    onVerifyRef.current = onVerify
  })
  useEffect(() => {
    onExpiredRef.current = onExpired
  })
  useEffect(() => {
    localeRef.current = locale
  })

  useEffect(() => {
    if (!siteKey) return
    let cancelled = false

    loadTurnstileApi().then((api) => {
      if (cancelled || !containerRef.current) return
      widgetIdRef.current = api.render(containerRef.current, {
        sitekey: siteKey,
        // Cloudflare lists `ur` directly; every other locale gets `auto`.
        language: localeRef.current === 'ur' ? 'ur' : 'auto',
        callback: (token: string) => onVerifyRef.current(token),
        'expired-callback': () => onExpiredRef.current?.(),
      })
    })

    return () => {
      cancelled = true
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current)
        widgetIdRef.current = null
      }
    }
  }, [siteKey])

  useEffect(() => {
    if (resetNonce === 0 || !widgetIdRef.current || !window.turnstile) return
    window.turnstile.reset(widgetIdRef.current)
  }, [resetNonce])

  if (!siteKey) return null

  // ~65px reserves the widget's own height so the form does not jump when the
  // challenge appears; Turnstile draws its own label inside the iframe.
  return (
    <div
      ref={containerRef}
      className={className}
      aria-label="Security check"
      style={{ minHeight: 65 }}
    />
  )
}
