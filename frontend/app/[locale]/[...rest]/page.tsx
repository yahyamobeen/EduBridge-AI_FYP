import { notFound } from 'next/navigation'

/**
 * Catch-all so an unmatched path under a locale renders the LOCALIZED 404
 * rather than Next's untranslated default. Real routes are more specific and
 * take precedence, so adding pages in later phases needs no change here.
 */
export default function CatchAll() {
  notFound()
}
