'use client'

import { useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api/client'

export type AuthorizedImage =
  { status: 'loading' } | { status: 'ready'; url: string } | { status: 'error' }

/**
 * An authenticated image, fetched through the API client and returned as a `data:` URI.
 *
 * ⚠️ WHY NOT A PLAIN `<img src>`: the tutor's figure crops and page scans are
 * authenticated and owner-scoped, and the access token lives in a module variable, not a
 * cookie, so a browser `<img>` request carries no `Authorization` header and the server
 * answers 401. `apiFetch` attaches the bearer token and carries the proactive-refresh and
 * retry-once contract.
 *
 * ⚠️ WHY `data:` AND NOT `URL.createObjectURL`: the CSP is `img-src 'self' data:`
 * (`next.config.mjs`) and does NOT list `blob:`, so an object URL would swap a 401 for a
 * CSP violation and still render nothing.
 *
 * `path` is base-relative (`/tutor/...`): `apiFetch` prepends the API base itself, so an
 * `/api/...` url from the server would become `/api/api/...` and 404.
 *
 * The result is keyed by the path it was fetched for, so a render never shows bytes that
 * belong to a different image - without clearing state at the top of the effect, which
 * `react-hooks/set-state-in-effect` rejects.
 */
export function useAuthorizedImage(path: string): AuthorizedImage {
  const [result, setResult] = useState<{ path: string; image: AuthorizedImage } | null>(null)

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
        // land after the component is gone.
        if (active) setResult({ path, image: { status: 'ready', url } })
      })
      .catch(() => {
        if (active) setResult({ path, image: { status: 'error' } })
      })

    return () => {
      active = false
    }
  }, [path])

  if (!result || result.path !== path) return { status: 'loading' }
  return result.image
}
