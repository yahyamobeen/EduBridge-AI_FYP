import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { PhysicsChatView } from './PhysicsChatView'

vi.mock('@/lib/api/endpoints', () => ({
  chatClass9Physics: vi.fn(),
}))

import { chatClass9Physics } from '@/lib/api/endpoints'

function renderChat({
  onBack = vi.fn(),
  onClose = vi.fn(),
}: {
  onBack?: () => void
  onClose?: () => void
} = {}) {
  return {
    onBack,
    onClose,
    ...render(
      <NextIntlClientProvider locale="en" messages={en}>
        <PhysicsChatView onBack={onBack} onClose={onClose} />
      </NextIntlClientProvider>,
    ),
  }
}

describe('PhysicsChatView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders title, welcome greeting, and quick prompt chips', () => {
    renderChat()

    expect(screen.getByText(en.tutor.chat.title)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.welcome)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.chip1)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.chip2)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.chip3)).toBeInTheDocument()
    expect(screen.getByText(en.tutor.chat.chip4)).toBeInTheDocument()
  })

  it('clicking a quick prompt chip sends the message immediately', async () => {
    vi.mocked(chatClass9Physics).mockResolvedValueOnce({
      reply: 'A thermocouple works on Seebeck effect.',
      pages: [
        {
          page: 155,
          chapter: 7,
          score: 0.95,
          url: '/api/tutor/class9/physics/pages/155',
        },
      ],
      timings: { search: 10 },
      gen_error: null,
    })

    renderChat()

    // Click chip 1 ("How does a thermocouple work?")
    const chip = screen.getByText(en.tutor.chat.chip1)
    fireEvent.click(chip)

    await waitFor(() => {
      expect(chatClass9Physics).toHaveBeenCalledWith({
        message: en.tutor.chat.chip1,
        lang: 'en',
        history: [{ role: 'user', content: en.tutor.chat.chip1 }],
      })
    })

    await waitFor(() => {
      expect(screen.getByText('A thermocouple works on Seebeck effect.')).toBeInTheDocument()
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
    })
  })

  it('allows switching response language before sending', async () => {
    vi.mocked(chatClass9Physics).mockResolvedValueOnce({
      reply: 'Pascal ka qanoon ye bayan karta hai...',
      pages: [],
      timings: { search: 5 },
      gen_error: null,
    })

    renderChat()

    // Switch language to Roman
    const romanBtn = screen.getByText('Roman')
    fireEvent.click(romanBtn)

    // Type query and send
    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: 'Pascal ka qanoon kya hai?' } })
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      expect(chatClass9Physics).toHaveBeenCalledWith({
        message: 'Pascal ka qanoon kya hai?',
        lang: 'ur-Latn',
        history: [{ role: 'user', content: 'Pascal ka qanoon kya hai?' }],
      })
    })
  })

  it('opens page scan preview dialog when citation is clicked', async () => {
    vi.mocked(chatClass9Physics).mockResolvedValueOnce({
      reply: 'See chapter 7 page 155.',
      pages: [
        {
          page: 155,
          chapter: 7,
          score: 0.95,
          url: '/api/tutor/class9/physics/pages/155',
        },
      ],
      timings: { search: 8 },
      gen_error: null,
    })

    renderChat()

    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: 'Show thermocouple diagram' } })
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
    })

    // Click the citation button
    const citationBtn = screen.getByText(/Page 155/).closest('button')!
    fireEvent.click(citationBtn)

    // Preview dialog should open
    expect(screen.getByText(/Page 155 \(PCTB Physics 9\)/)).toBeInTheDocument()
    const img = screen.getByAltText(/Textbook Page 155/)
    expect(img).toHaveAttribute('src', '/api/tutor/class9/physics/pages/155')

    // Close preview
    const closeBtns = screen.getAllByLabelText('Close')
    fireEvent.click(closeBtns[closeBtns.length - 1]!)

    expect(screen.queryByText(/Page 155 \(PCTB Physics 9\)/)).not.toBeInTheDocument()
  })

  it('displays error message and retry button on network failure', async () => {
    vi.mocked(chatClass9Physics).mockRejectedValueOnce(new Error('Network error'))

    renderChat()

    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: 'Force formula' } })
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      expect(screen.getByText(en.tutor.chat.errorFallback)).toBeInTheDocument()
      expect(screen.getByText(en.tutor.chat.retry)).toBeInTheDocument()
    })

    // Resolves on retry
    vi.mocked(chatClass9Physics).mockResolvedValueOnce({
      reply: 'F = ma',
      pages: [],
      timings: {},
      gen_error: null,
    })

    fireEvent.click(screen.getByText(en.tutor.chat.retry))

    await waitFor(() => {
      expect(screen.getByText('F = ma')).toBeInTheDocument()
    })
  })

  it('triggers onBack and onClose callbacks', () => {
    const { onBack, onClose } = renderChat()

    fireEvent.click(screen.getByLabelText('Back'))
    expect(onBack).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
