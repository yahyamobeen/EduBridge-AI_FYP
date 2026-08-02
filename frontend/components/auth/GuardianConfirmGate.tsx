'use client'

import { useEffect, useState } from 'react'
import { GuardianConfirm } from '@/components/auth/GuardianConfirm'
import { getMe } from '@/lib/api/endpoints'

/**
 * Works out whether the visitor already has a parent session before rendering
 * the confirmation.
 *
 * The parent arrives from an email link, usually in a fresh tab, so the access
 * token — which lives only in memory — is gone. The refresh cookie is not, and
 * `apiFetch` recovers a session from it automatically on the first 401. Asking
 * the identity endpoint is therefore both the session check and the recovery.
 *
 * A `role` other than `parent` is treated as signed-out for this purpose: a
 * student who opens their own invitation must not be offered a confirm button,
 * because the server would reject it and the offer implies they could forge the
 * gate (tdd.md §3.1).
 */
export function GuardianConfirmGate({ token }: { token: string | null }) {
  const [signedIn, setSignedIn] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const me = await getMe()
        if (!cancelled) setSignedIn(me.role === 'parent')
      } catch {
        if (!cancelled) setSignedIn(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Nothing is rendered until the answer is known: showing "sign up first" and
  // then swapping in a confirm button would invite a mis-click on a control the
  // parent did not mean to press.
  if (signedIn === null) return null

  return <GuardianConfirm token={token} signedIn={signedIn} />
}
