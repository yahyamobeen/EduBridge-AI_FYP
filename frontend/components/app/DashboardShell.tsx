'use client'

import { useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { LanguageSwitcher } from '@/components/layout/LanguageSwitcher'
import { ArrowIcon } from '@/components/ui/Icon'
import { Link, usePathname, useRouter } from '@/i18n/navigation'
import { logout } from '@/lib/api/endpoints'
import type { MeResponse } from '@/lib/api/types'
import { avatarInitial, displayName } from '@/lib/auth/displayName'
import { navFor, ROLE_ACCENT, type NavItem } from '@/lib/auth/navigation'

/**
 * The item that owns `pathname`: the one whose href is the LONGEST prefix of it,
 * so `/teacher/classroom/<id>` is My classrooms, not the Dashboard at
 * `/teacher`. No match marks nothing, rather than guessing. (It used to be the
 * first item on every page — so a classroom showed "Dashboard" as current.)
 */
export function currentItem(items: NavItem[], pathname: string): NavItem | null {
  let best: NavItem | null = null
  for (const item of items) {
    const owns = pathname === item.href || pathname.startsWith(`${item.href}/`)
    if (owns && (best === null || item.href.length > best.href.length)) best = item
  }
  return best
}

/**
 * The dashboard chrome: the prototype's 256px docked sidebar, the identity
 * block, the nav list, and the sign-out footer.
 *
 * EVERY ITEM COMES FROM `NAV_BY_ROLE`. The three dashboard mockups shipped one
 * identical student sidebar, which is how a parent ended up with an AI-tutor
 * replay button; building the list from the map instead of from the markup is
 * what makes that impossible to reintroduce by copy-paste.
 *
 * The prototype's avatar is a photograph from a Google CDN. It is replaced by
 * an initial: a third-party image request in the critical path is against
 * prd.md A11Y-2, the CSP allows `img-src 'self' data:` only, and there is no
 * avatar field in the contract to put a real one in.
 */
export function DashboardShell({
  me,
  subtitle,
  children,
}: {
  me: MeResponse
  subtitle: string
  children: ReactNode
}) {
  const t = useTranslations('nav.items')
  const tApp = useTranslations('app')
  const tDash = useTranslations('dashboard')
  const router = useRouter()
  const pathname = usePathname()
  // The page the phone menu was opened on. Since Phase 6c the shell lives in
  // the (app) layout and is no longer remounted by a navigation, so "open" is
  // derived from it: following a menu link changes the page and closes the
  // menu, with no effect and no setState on navigation.
  const [openOn, setOpenOn] = useState<string | null>(null)
  const open = openOn === pathname

  const items = navFor(me.role)
  const current = currentItem(items, pathname)
  const accent = ROLE_ACCENT[me.role]
  const initial = avatarInitial(me)

  /**
   * The redirect must happen on BOTH paths.
   *
   * `logout()` clears the in-memory session in a `finally` and then RE-THROWS,
   * deliberately — dropping the local session matters more than the server call
   * succeeding. Awaiting it without a `catch` meant a network failure threw
   * here, `router.replace` never ran, and the dashboard stayed on screen fully
   * rendered, because `me` is already in state and `SessionGuard` has already
   * passed. The user clicked "sign out", nothing changed, and on the shared
   * devices prd.md §3.1 describes they walk away from a page still showing
   * their name and their child's progress.
   */
  async function signOut() {
    try {
      await logout()
    } catch {
      // Nothing to recover: the token is already gone. Swallowed rather than
      // surfaced, because the user asked to leave and the next screen is the
      // sign-in page either way.
    } finally {
      router.replace('/login')
    }
  }

  const nav = (
    <>
      <div className="mb-8">
        <p className={`font-headline text-headline-md font-bold ${accent}`}>{tApp('name')}</p>
      </div>

      <div className="mb-8 flex items-center gap-4">
        <span
          aria-hidden="true"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-container-highest font-headline text-headline-md text-on-surface-variant"
        >
          {initial}
        </span>
        <div className="min-w-0">
          <p className="truncate font-headline text-body-lg text-on-surface">
            {displayName(me)}
          </p>
          <p className="truncate text-body-sm text-on-surface-variant">{subtitle}</p>
        </div>
      </div>

      <ul className="flex-grow space-y-2">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              aria-current={item === current ? 'page' : undefined}
              className={
                item === current
                  ? 'block rounded bg-primary-container px-4 py-2 font-semibold text-on-primary-container'
                  : 'block rounded px-4 py-2 text-on-surface-variant transition-colors hover:bg-surface-variant'
              }
            >
              {t(item.key)}
            </Link>
          </li>
        ))}
      </ul>

      <div className="mt-auto space-y-4 border-t border-outline-variant pt-4">
        <LanguageSwitcher />
        <button
          type="button"
          onClick={signOut}
          className="block w-full rounded px-4 py-2 text-start text-on-surface-variant transition-colors hover:bg-surface-variant"
        >
          {t('logout')}
        </button>
      </div>
    </>
  )

  return (
    <div className="flex min-h-screen">
      {/* Docked sidebar, 256px, from md up — as measured in the prototype. */}
      <nav
        aria-label={tDash('primaryNav')}
        className="sticky top-0 hidden h-screen w-64 flex-col border-e border-outline-variant bg-surface-container-low p-4 md:flex"
      >
        {nav}
      </nav>

      {/* Below md the prototype has no navigation at all, which would strand a
          phone user. A disclosure keeps the same items reachable. */}
      <div className="md:hidden">
        <button
          type="button"
          onClick={() => setOpenOn(open ? null : pathname)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          className="fixed bottom-4 end-4 z-20 rounded-full bg-primary px-5 py-3 text-label-caps uppercase text-on-primary shadow-lg"
        >
          {open ? tDash('closeMenu') : tDash('openMenu')}
        </button>
        {open && (
          <div
            id="mobile-nav"
            className="fixed inset-0 z-10 flex flex-col overflow-y-auto bg-surface-container-low p-4"
          >
            {nav}
          </div>
        )}
      </div>

      <div className="flex-grow overflow-y-auto p-gutter md:p-margin-desktop">{children}</div>
    </div>
  )
}

/**
 * A dashboard panel with no data behind it yet.
 *
 * No dashboard endpoint exists (plan assumption A3), so these say so rather
 * than showing invented figures. A screenshot of fabricated analytics is the
 * kind of thing that ends up in a demo and then in a report.
 */
export function PlaceholderCard({
  title,
  body,
  span = 4,
  href,
}: {
  title: string
  body: string
  span?: 4 | 6 | 8 | 12
  href?: string
}) {
  const t = useTranslations('dashboard')
  const cols = {
    4: 'md:col-span-4',
    6: 'md:col-span-6',
    8: 'md:col-span-8',
    12: 'md:col-span-12',
  }[span]

  return (
    <section
      className={`col-span-1 rounded-md border border-outline-variant bg-surface p-6 ${cols}`}
    >
      <h3 className="mb-2 font-headline text-headline-md text-on-surface">{title}</h3>
      <p className="mb-4 text-body-sm text-on-surface-variant">{body}</p>
      <p className="inline-flex items-center gap-2 rounded-full bg-surface-container px-3 py-1 text-label-caps uppercase text-on-surface-variant">
        {t('notYetAvailable')}
      </p>
      {href && (
        <div className="mt-4">
          <Link
            href={href}
            className="inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:text-primary-container"
          >
            {t('learnMore')}
            <ArrowIcon className="h-4 w-4 rtl:-scale-x-100" />
          </Link>
        </div>
      )}
    </section>
  )
}
