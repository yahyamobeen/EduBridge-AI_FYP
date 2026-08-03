'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { useRouter } from '@/i18n/navigation'
import { getMe } from '@/lib/api/endpoints'
import type { MeResponse, Role } from '@/lib/api/types'
import { dashboardFor, routeForOnboardingState } from '@/lib/auth/onboarding'

/**
 * The gate on every authenticated route.
 *
 * THE RULE THAT MAKES THIS DIFFERENT FROM THE OBVIOUS IMPLEMENTATION:
 * onboarding is NOT monotonic. A student reaches `active`, uses the app for
 * fourteen days, and then the trial lapses and the server puts them back into
 * `plan_selection_pending` (prd.md §2.6 MON-4). So the state is re-read on
 * every mount and never cached as "already checked" — a guard written as "check
 * once, then trust" is wrong here, and it is exactly what most people write.
 *
 * Three checks, in this order:
 *   1. no session            -> /login
 *   2. onboarding incomplete -> the step that completes it
 *   3. wrong role for route  -> that role's own dashboard
 *
 * None of this is a security control. The gate is enforced at the API and RLS
 * layers (tdd.md §3.1), so calling the endpoint directly is still refused; this
 * only stops the UI showing a user a page they cannot use.
 */
export function SessionGuard({
  children,
  allow,
}: {
  children: (me: MeResponse) => ReactNode
  /** Roles permitted on this route. */
  allow: Role[]
}) {
  const t = useTranslations('app')
  const router = useRouter()
  const [me, setMe] = useState<MeResponse | null>(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    // ONE identity check per mount, expressed as an EMPTY dependency array
    // rather than a `started` ref.
    //
    // THE REF VERSION DEADLOCKED IN DEVELOPMENT. `reactStrictMode` makes React
    // mount, unmount and remount every component. The unmount set `cancelled`,
    // discarding the in-flight response; the remount found `started.current`
    // still true -- refs survive the double-invoke -- and returned early. So
    // the first request's result was thrown away, the second request was never
    // made, and neither `setMe` nor `setChecked` ever ran. Every dashboard sat
    // on "Loading..." forever, for every role, with a perfectly healthy 200
    // sitting in the network tab.
    //
    // It only happened in development, which is the worst place for a bug to
    // hide: the production build was fine, so nothing in CI could see it.
    let cancelled = false

    void (async () => {
      try {
        const identity = await getMe()
        if (cancelled) return

        if (identity.onboarding_state !== 'active') {
          router.replace(routeForOnboardingState(identity.onboarding_state, identity.role))
          return
        }
        if (!allow.includes(identity.role)) {
          router.replace(dashboardFor(identity.role))
          return
        }
        setMe(identity)
      } catch {
        // Any failure to establish identity is treated as "not signed in". The
        // client has already tried a refresh by this point (lib/api/client.ts),
        // so there is nothing further to recover from.
        if (!cancelled) router.replace('/login')
      } finally {
        if (!cancelled) setChecked(true)
      }
    })()

    return () => {
      cancelled = true
    }
    // Deliberately empty. `allow` is a literal at every call site, and
    // `router` is a fresh object on every render -- keying on it would re-run
    // the identity check continuously, a stream of duplicate requests nobody
    // asked for on a connection prd.md A11Y-2 says to respect. Capturing it
    // from the first render is safe: its methods delegate to the app-router
    // singleton, not to the object.
    //
    // Remounting still re-checks, which is the point: onboarding is not
    // monotonic, so the state is re-read on entry and never remembered across
    // one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (me === null) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-[60vh] items-center justify-center px-gutter"
      >
        <p className="text-body-md text-on-surface-variant">
          {checked ? t('redirecting') : t('loading')}
        </p>
      </div>
    )
  }

  return <>{children(me)}</>
}
