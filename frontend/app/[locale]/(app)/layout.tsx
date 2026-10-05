import type { ReactNode } from 'react'
import { AppFrame } from '@/components/app/AppFrame'

/**
 * The authenticated application.
 *
 * The frame — the identity check and the role's sidebar — is rendered HERE,
 * once, so it stays mounted while the pages change inside it (classroom Phase
 * 6c). Until then each page rendered its own guard and sidebar, so every
 * navigation blanked the screen to "Loading…" and rebuilt the sidebar. The
 * identity is still re-read on every navigation (onboarding is not monotonic,
 * see `SessionGuard`), in the background; each page checks its own roles with
 * `RequireRole`.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="flex flex-1 flex-col">
      <AppFrame>{children}</AppFrame>
    </main>
  )
}
