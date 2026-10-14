import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TutorFigure } from './TutorFigure'

vi.mock('@/lib/api/client', () => ({ apiFetch: vi.fn() }))

import { apiFetch } from '@/lib/api/client'

describe('TutorFigure', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches the crop through the authenticated client, not as a bare img src', async () => {
    // The defect: `<img src="/api/tutor/figures/x">` sends no Authorization header, so
    // the owner-scoped route answers 401 and the student sees a broken image.
    vi.mocked(apiFetch).mockResolvedValueOnce(new Blob(['xx'], { type: 'image/jpeg' }))

    render(<TutorFigure messageId="abc" alt="Fig. 5.10" caption="Fig. 5.10" />)

    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1))
    // ⚠️ BASE-RELATIVE, no `/api`. `apiFetch` prepends the API base, so passing the
    // frame's own `/api/tutor/figures/{id}` produced `/api/api/...` and a 404.
    expect(apiFetch).toHaveBeenCalledWith('/tutor/figures/abc', { responseType: 'blob' })
  })

  it('renders the crop as a data: URI, which is what the CSP permits', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Blob(['xx'], { type: 'image/jpeg' }))

    render(<TutorFigure messageId="abc" alt="Fig. 5.10" caption="Fig. 5.10" />)

    const img = await screen.findByAltText('Fig. 5.10')
    // `img-src 'self' data:` does NOT list blob:, so an object URL would be blocked.
    expect(img.getAttribute('src')).toMatch(/^data:image\/jpeg/)
    expect(screen.getByText('Fig. 5.10', { selector: 'figcaption' })).toBeInTheDocument()
  })

  it('renders nothing when the crop cannot be fetched', async () => {
    // A missing figure costs the picture, never the answer the student is reading.
    vi.mocked(apiFetch).mockRejectedValueOnce(new Error('403'))

    const { container } = render(<TutorFigure messageId="abc" alt="Fig. 5.10" />)

    await waitFor(() => expect(apiFetch).toHaveBeenCalled())
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('figure')).toBeNull()
  })
})
