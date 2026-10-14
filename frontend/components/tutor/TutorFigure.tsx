'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api/client'

/**
 * The cropped textbook figure for one answer.
 *
 * ⚠️ IT CANNOT BE A PLAIN `<img src={url}>`, WHICH IS WHAT IT WAS AND WHY IT SHOWED A
 * BROKEN IMAGE. `GET /api/tutor/figures/{message_id}` is authenticated and owner-scoped
 * — deliberately, unlike the page-scan route beside it (defect P1) — and the access
 * token lives in a module variable, not a cookie. A browser `<img>` request carries no
 * `Authorization` header, so the server answered 401 and the student saw a broken icon.
 * Measured: the figure route 401s on a header-less request while the page-scan route
 * returns 200, which is exactly why page thumbnails worked and this did not.
 *
 * So the bytes are fetched through the ordinary API client — which attaches the bearer
 * token and carries the proactive-refresh and retry-once contract — and handed to the
 * tag as a `data:` URI.
 *
 * ⚠️ A `data:` URI rather than `URL.createObjectURL`, because the CSP is
 * `img-src 'self' data:` (`next.config.mjs`) and does NOT list `blob:` — an object URL
 * would swap a 401 for a CSP violation and still render nothing. `data:` is already
 * permitted, so this needs no security-header change.
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
  const path = `/tutor/figures/${messageId}`
  // Keyed by the path it was fetched for, so a render can tell whether the bytes in
  // hand belong to the figure currently being asked for. Clearing state at the top of
  // the effect would do the same job, but setState in an effect body triggers
  // cascading renders and `react-hooks/set-state-in-effect` rejects it.
  const [loaded, setLoaded] = useState<{ path: string; url: string } | null>(null)

  useEffect(() => {
    let active = true

    apiFetch<Blob>(path, { responseType: 'blob' })
      .then(
        (blob) =>
          new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () => resolve(reader.result as string)
            reader.onerror = () => reject(reader.error)
            reader.readAsDataURL(blob)
          }),
      )
      .then((url) => {
        // The message list re-renders on every streamed frame, so a resolved fetch can
        // land after this component is gone.
        if (active) setLoaded({ path, url })
      })
      .catch(() => {
        if (active) setLoaded(null)
      })

    return () => {
      active = false
    }
  }, [path])

  // Nothing yet, or bytes belonging to a figure we are no longer showing.
  if (!loaded || loaded.path !== path) return null

  return (
    <figure className="mt-3">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={loaded.url}
        alt={alt}
        className="max-h-64 w-auto rounded-lg border border-outline-variant/40 bg-surface"
      />
      {caption && (
        <figcaption className="mt-1 text-xs text-on-surface-variant">{caption}</figcaption>
      )}
    </figure>
  )
}
