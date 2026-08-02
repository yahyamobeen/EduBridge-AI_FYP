import type { ReactNode } from 'react'
import { Footer } from '@/components/layout/Footer'
import { TopNav } from '@/components/layout/TopNav'

/**
 * The public site shell: nav, content, footer.
 *
 * A route group adds no path segment, so every page under it keeps the URL it
 * had. The split exists so the transactional auth screens can opt out of the
 * chrome, which both of their prototypes do.
 */
export default function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <TopNav />
      <main id="main" className="flex-1">
        {children}
      </main>
      <Footer />
    </>
  )
}
