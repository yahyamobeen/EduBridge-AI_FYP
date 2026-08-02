import { createNavigation } from 'next-intl/navigation'
import { routing } from './routing'

/**
 * Locale-aware navigation. Always import Link/redirect/useRouter from here
 * rather than from `next/link` or `next/navigation`, or the locale prefix is
 * dropped and the user silently falls back to English mid-journey.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing)
