import type { ReactNode } from 'react'

/**
 * The authenticated application.
 *
 * No chrome here: each dashboard renders its own sidebar through
 * `DashboardShell`, because the sidebar's contents depend on the role, which is
 * only known once `SessionGuard` has resolved the identity.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="flex flex-1 flex-col">
      {children}
    </main>
  )
}
