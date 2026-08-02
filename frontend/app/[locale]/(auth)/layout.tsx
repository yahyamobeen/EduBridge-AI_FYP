import type { ReactNode } from 'react'

/**
 * Sign-in, the second factor, and the password and verification screens.
 *
 * Deliberately bare: no top nav, no footer. Both prototypes suppress them, and
 * the reason is sound — a half-authenticated user has nowhere legitimate to
 * navigate to, and offering the marketing nav mid-challenge is an invitation to
 * abandon the flow. Each screen carries its own minimal footer links instead.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="flex flex-1 flex-col">
      {children}
    </main>
  )
}
