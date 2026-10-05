import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { SubjectModal } from './SubjectModal'

vi.mock('@/lib/api/endpoints', () => ({
  chatClass9Physics: vi.fn(),
  getPhysicsTutorInfo: vi.fn(),
}))

import { chatClass9Physics } from '@/lib/api/endpoints'

function renderModal({
  isOpen = true,
  onClose = vi.fn(),
}: { isOpen?: boolean; onClose?: () => void } = {}) {
  return {
    onClose,
    ...render(
      <NextIntlClientProvider locale="en" messages={en}>
        <SubjectModal isOpen={isOpen} onClose={onClose} />
      </NextIntlClientProvider>,
    ),
  }
}

describe('SubjectModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when isOpen is false', () => {
    renderModal({ isOpen: false })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders the subject picker with all 6 subjects when open', () => {
    renderModal({ isOpen: true })

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(en.tutor.modal.title)).toBeInTheDocument()

    // All 6 subjects
    expect(screen.getByText(en.tutor.subjects.physics)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.subjects.mathematics)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.subjects.chemistry)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.subjects.english)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.subjects.urdu)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.subjects.islamiyat)).toBeInTheDocument()

    // Status badges
    expect(screen.getByText(en.tutor.modal.availableBadge)).toBeInTheDocument()
    expect(screen.getAllByText(en.tutor.modal.comingSoonBadge)).toHaveLength(5)
  })

  it('displays the coming soon dialogue when a non-physics subject is clicked', () => {
    renderModal({ isOpen: true })

    const mathButton = screen.getByText(en.tutor.subjects.mathematics).closest('button')!
    fireEvent.click(mathButton)

    // Heading and coming soon notice should be displayed
    expect(screen.getByText(en.tutor.modal.comingSoonTitle)).toBeInTheDocument()
    expect(
      screen.getByText(
        en.tutor.modal.comingSoonNotice.replace('{subject}', en.tutor.subjects.mathematics),
      ),
    ).toBeInTheDocument()

    // Clicking "Back" returns to the subject picker
    const backBtn = screen.getByText(en.tutor.modal.back).closest('button')!
    fireEvent.click(backBtn)

    expect(screen.getByText(en.tutor.modal.title)).toBeInTheDocument()
  })

  it('transitions to the Physics Chat View when Physics is clicked', async () => {
    renderModal({ isOpen: true })

    const physicsButton = screen.getByText(en.tutor.subjects.physics).closest('button')!
    fireEvent.click(physicsButton)

    // Chat view components should appear
    expect(screen.getByText(en.tutor.chat.title)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.chip1)).toBeInTheDocument()
  })

  it('sends a message and renders response with page citations in physics chat', async () => {
    vi.mocked(chatClass9Physics).mockResolvedValueOnce({
      reply: "Newton's first law states that an object remains at rest unless acted upon.",
      pages: [
        {
          page: 58,
          chapter: 3,
          score: 0.92,
          url: '/api/tutor/class9/physics/pages/58',
        },
      ],
      timings: { search: 12 },
      gen_error: null,
    })

    renderModal({ isOpen: true })

    // Open physics
    const physicsButton = screen.getByText(en.tutor.subjects.physics).closest('button')!
    fireEvent.click(physicsButton)

    // Type query and send
    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: "State Newton's first law" } })

    const sendBtn = screen.getByLabelText(en.tutor.chat.send)
    fireEvent.click(sendBtn)

    // Verify chatClass9Physics was called
    await waitFor(() => {
      expect(chatClass9Physics).toHaveBeenCalledWith({
        message: "State Newton's first law",
        lang: 'en',
        history: [{ role: 'user', content: "State Newton's first law" }],
      })
    })

    // Verify answer and citation chip rendered
    await waitFor(() => {
      expect(
        screen.getByText(
          "Newton's first law states that an object remains at rest unless acted upon.",
        ),
      ).toBeInTheDocument()
      expect(screen.getByText(/Page 58/)).toBeInTheDocument()
    })
  })

  it('invokes onClose when the close button is clicked', () => {
    const { onClose } = renderModal({ isOpen: true })

    const closeBtn = screen.getByLabelText(en.tutor.modal.close)
    fireEvent.click(closeBtn)

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
