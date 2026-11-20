'use client'

import { useAuthorizedImage } from './useAuthorizedImage'

/**
 * The cropped textbook figure for one answer.
 *
 * ⚠️ IT CANNOT BE A PLAIN `<img src={url}>`, WHICH IS WHAT IT WAS AND WHY IT SHOWED A
 * BROKEN IMAGE. `GET /api/tutor/figures/{message_id}` is authenticated and owner-scoped,
 * and the access token lives in a module variable, not a cookie. A browser `<img>`
 * request carries no `Authorization` header, so the server answered 401 and the student
 * saw a broken icon. The bytes are fetched through the API client instead and handed to
 * the tag as a `data:` URI - `useAuthorizedImage` holds the reasoning, shared with the
 * page-scan preview (`TutorPageImage`).
 *
 * A failure renders NOTHING rather than a broken image: the figure is an illustration of
 * an answer the student can already read, so a missing crop should cost the picture, not
 * put an error in the middle of the prose.
 */
export function TutorFigure({
  messageId,
  alt,
  caption,
}: {
  messageId: string
  alt: string
  caption?: string
}) {
  // Built here, NOT taken from the `figure` frame's `url`. That field is
  // `/api/tutor/figures/{id}` — correct for a browser, wrong for `apiFetch`, which
  // prepends the API base itself and produced `/api/api/tutor/figures/{id}` → 404.
  // Every other call in `endpoints.ts` passes a base-relative path; this matches.
  const image = useAuthorizedImage(`/tutor/figures/${messageId}`)

  if (image.status !== 'ready') return null

  return (
    <figure className="mt-3">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={image.url}
        alt={alt}
        className="max-h-64 w-auto rounded-lg border border-outline-variant/40 bg-surface"
      />
      {caption && (
        <figcaption className="mt-1 text-xs text-on-surface-variant">{caption}</figcaption>
      )}
    </figure>
  )
}
