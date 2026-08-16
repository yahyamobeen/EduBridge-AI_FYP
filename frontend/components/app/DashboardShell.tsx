'use client'

import { useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { LanguageSwitcher } from '@/components/layout/LanguageSwitcher'
import { ArrowIcon } from '@/components/ui/Icon'
import { Link, useRouter } from '@/i18n/navigation'
import { logout } from '@/lib/api/endpoints'
import type { MeResponse } from '@/lib/api/types'
import { navFor, ROLE_ACCENT } from '@/lib/auth/navigation'

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
  const [open, setOpen] = useState(false)

  const items = navFor(me.role)
  const accent = ROLE_ACCENT[me.role]
  const initial = me.full_name.trim().charAt(0).toUpperCase() || '?'

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
          <p className="truncate font-headline text-body-lg text-on-surface">{me.full_name}</p>
          <p className="truncate text-body-sm text-on-surface-variant">{subtitle}</p>
        </div>
      </div>

      <ul className="flex-grow space-y-2">
        {items.map((item, index) => (
          <li key={item.key}>
            <Link
              href={item.href}
              aria-current={index === 0 ? 'page' : undefined}
              className={
                index === 0
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
          onClick={() => setOpen((v) => !v)}
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
