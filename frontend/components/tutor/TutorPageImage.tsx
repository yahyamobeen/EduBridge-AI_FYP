'use client'

import { useTranslations } from 'next-intl'
import { tutorPagePath } from '@/lib/api/endpoints'
import { useAuthorizedImage } from './useAuthorizedImage'

/**
 * One page scan of one book, for a citation preview (tdd.md §3.2a "Many books").
 *
 * The page route is authenticated and checks the caller owns the book, so the scan is
 * fetched through `useAuthorizedImage` - see that hook for why a plain `<img src>` and
 * an object URL both fail here.
 */
export function TutorPageImage({ bookId, page }: { bookId: string; page: number }) {
  const t = useTranslations('tutor.chat')
  const image = useAuthorizedImage(tutorPagePath(bookId, page))

  if (image.status === 'loading') {
    return (
      <p role="status" className="py-12 text-center text-body-sm text-on-surface-variant">
        {t('loadingPage')}
      </p>
    )
  }
  if (image.status === 'error') {
    return (
      <p role="alert" className="py-12 text-center text-body-sm text-on-surface-variant">
        {t('pageError')}
      </p>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={image.url}
      alt={t('pageAlt', { page })}
      className="mx-auto h-auto max-w-full rounded shadow"
    />
  )
}
