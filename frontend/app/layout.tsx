import type { ReactNode } from 'react'

/**
 * Next requires a layout at the top of `app/`, but `<html>` cannot live here:
 * `lang` and `dir` both depend on the locale, which is only known inside the
 * `[locale]` segment. This is a pass-through; the real document shell is
 * `app/[locale]/layout.tsx`.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children
}
