import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { TutorPageImage } from './TutorPageImage'

// The page route is authenticated, so the scan goes through `apiFetch` (bearer token,
// refresh contract). Only `apiFetch` is stubbed; the rest of the client stays real.
vi.mock('@/lib/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/client')>()),
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/api/client'

function renderPage(bookId = 'Sindh_10_Chemistry', page = 26) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <TutorPageImage bookId={bookId} page={page} />
    </NextIntlClientProvider>,
  )
}

describe('TutorPageImage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("fetches the book's page with the bearer token and shows it as a data: URI", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Blob(['jpegbytes'], { type: 'image/jpeg' }))
    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent(en.tutor.chat.loadingPage)
    const img = await screen.findByAltText(en.tutor.chat.pageAlt.replace('{page}', '26'))
    // data:, never blob: - the CSP is `img-src 'self' data:`.
    expect(img.getAttribute('src')).toMatch(/^data:image\/jpeg;base64,/)
    // Base-relative: apiFetch adds the API base itself.
    expect(apiFetch).toHaveBeenCalledWith('/tutor/books/Sindh_10_Chemistry/pages/26', {
      responseType: 'blob',
    })
  })

  it('says so when the page cannot be loaded', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('403'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent(en.tutor.chat.pageError)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('encodes the book id into the path', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Blob(['x'], { type: 'image/jpeg' }))
    renderPage('a/b', 1)
    await screen.findByRole('img')
    expect(apiFetch).toHaveBeenCalledWith('/tutor/books/a%2Fb/pages/1', {
      responseType: 'blob',
    })
  })
})
