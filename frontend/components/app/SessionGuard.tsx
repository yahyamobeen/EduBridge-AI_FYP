'use client'

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { usePathname, useRouter } from '@/i18n/navigation'
import { getMe } from '@/lib/api/endpoints'
import type { MeResponse, Role } from '@/lib/api/types'
import { dashboardFor, routeForOnboardingState } from '@/lib/auth/onboarding'

/**
 * The gate on every authenticated route, in two parts since classroom Phase 6c.
 *
 * `SessionGuard` lives in the `(app)` layout (through `AppFrame`) and answers
 * "who is this, and is their journey complete?". `RequireRole` lives in each
 * page and answers "may this role see this page?". The guard — and the sidebar
 * it carries — stays mounted while the pages change under it; before Phase 6c
 * every page wrapped itself in its own guard and sidebar, so each navigation
 * blanked the screen to "Loading…" and rebuilt the sidebar (owner report,
 * 2026-10-05).
 *
 * THE RULE THAT MAKES THIS DIFFERENT FROM THE OBVIOUS IMPLEMENTATION:
 * onboarding is NOT monotonic. A student reaches `active`, uses the app for
 * fourteen days, and then the trial lapses and the server puts them back into
 * `plan_selection_pending` (prd.md §2.6 MON-4). So the state is re-read on
 * EVERY NAVIGATION and never cached as "already checked" — a guard written as
 * "check once, then trust" is wrong here, and it is exactly what most people
 * write. What Phase 6c changed is only what the user sees meanwhile: the page
 * and the sidebar stay on screen while the re-check runs (stale while
 * revalidating), and a redirect follows if the state has gone backwards.
 *
 * Three checks, in this order:
 *   1. no session            -> /login                         (SessionGuard)
 *   2. onboarding incomplete -> the step that completes it      (SessionGuard)
 *   3. wrong role for route  -> that role's own dashboard       (RequireRole)
 *
 * None of this is a security control. The gate is enforced at the API and RLS
 * layers (tdd.md §3.1), so calling the endpoint directly is still refused; this
 * only stops the UI showing a user a page they cannot use.
 */

const MeContext = createContext<MeResponse | null>(null)

export function SessionGuard({ children }: { children: (me: MeResponse) => ReactNode }) {
  const t = useTranslations('app')
  const router = useRouter()
  const pathname = usePathname()
  const [me, setMe] = useState<MeResponse | null>(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    // ONE identity check per navigation, keyed on the path, rather than a
    // `started` ref.
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
    // Keyed on the path ONLY. `router` is a fresh object on every render --
    // keying on it would re-run the identity check continuously, a stream of
    // duplicate requests nobody asked for on a connection prd.md A11Y-2 says to
    // respect. Capturing it from the first render is safe: its methods
    // delegate to the app-router singleton, not to the object.
    //
    // A new path re-checks, which is the point: onboarding is not monotonic,
    // so the state is re-read on every entry to a page and never remembered.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  // Only the FIRST check blanks the screen: until it answers there is no
  // identity to show, and fail-closed means no page content either.
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

  return <MeContext.Provider value={me}>{children(me)}</MeContext.Provider>
}

/** The signed-in identity, for a component inside `SessionGuard`. */
export function useMe(): MeResponse {
  const me = useContext(MeContext)
  if (me === null) throw new Error('useMe() is only available inside <SessionGuard>.')
  return me
}

/**
 * The page's own role list — check 3. A wrong role is sent to its own
 * dashboard and sees no page content meanwhile; the identity comes from the
 * layout's `SessionGuard`, so there is no second request and no flash.
 */
export function RequireRole({
  allow,
  children,
}: {
  /** Roles permitted on this route. */
  allow: Role[]
  children: (me: MeResponse) => ReactNode
}) {
  const t = useTranslations('app')
  const router = useRouter()
  const me = useMe()
  const allowed = allow.includes(me.role)

  useEffect(() => {
    if (!allowed) router.replace(dashboardFor(me.role))
    // `allow` is a literal at every call site and `router` a fresh object per
    // render (see above); the decision is `allowed` and the target `me.role`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed, me.role])

  if (!allowed) {
    return (
      <p role="status" className="text-body-md text-on-surface-variant">
        {t('redirecting')}
      </p>
    )
  }
  return <>{children(me)}</>
}
