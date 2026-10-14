import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { PhysicsChatView } from './PhysicsChatView'

vi.mock('@/lib/api/endpoints', () => ({
  askTutor: vi.fn(),
  listTutorSessions: vi.fn(),
  getTutorSession: vi.fn(),
}))

// TutorFigure fetches the crop through the authenticated client, because the figure
// route is owner-scoped and an `<img>` cannot send a bearer token. Only `apiFetch` is
// stubbed; the rest of the client stays real.
vi.mock('@/lib/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/client')>()),
  apiFetch: vi.fn(),
}))

import { askTutor, getTutorSession, listTutorSessions } from '@/lib/api/endpoints'
import { apiFetch } from '@/lib/api/client'
import type { PageCitation, RetrieverTier, TurnIntent } from '@/lib/api/types'

/**
 * The real frame sequence: one `pages`, a `token` per chunk, one `done`.
 *
 * Chunked on purpose rather than one big token - a parser or a reducer that
 * only works when the whole answer arrives at once is exactly the bug this
 * shape catches.
 */
function streamOf({
  pages = [],
  chunks = ['ok'],
  retriever = 'remote',
  intent = 'retrieve',
  error = null,
  sessionId = 'sess-1',
}: {
  pages?: PageCitation[]
  chunks?: string[]
  retriever?: RetrieverTier
  intent?: TurnIntent
  error?: string | null
  sessionId?: string
} = {}) {
  return (async function* () {
    yield { event: 'pages', data: { pages, retriever, intent, timings: { search: 0.01 } } }
    for (const text of chunks) yield { event: 'token', data: { text } }
    yield {
      event: 'done',
      data: { session_id: sessionId, message_id: 'msg-1', timings: {}, error },
    }
  })()
}

const PAGE_155: PageCitation = {
  page: 155,
  chapter: 7,
  score: 18.4,
  url: '/api/tutor/class9/physics/pages/155',
}

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
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ pages: [PAGE_155], chunks: ['A thermocouple works on Seebeck effect.'] }),
    )

    renderChat()

    // Click chip 1 ("How does a thermocouple work?")
    const chip = screen.getByText(en.tutor.chat.chip1)
    fireEvent.click(chip)

    await waitFor(() => {
      // ⚠️ No `history`. The server reads the transcript it stored; sending a
      // client-supplied one would let this component put words in the
      // assistant's mouth and have the model treat them as its own answer.
      expect(askTutor).toHaveBeenCalledWith({
        message: en.tutor.chat.chip1,
        lang: 'en',
        session_id: null,
      })
    })

    await waitFor(() => {
      expect(screen.getByText('A thermocouple works on Seebeck effect.')).toBeInTheDocument()
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
    })
  })

  it('allows switching response language before sending', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ chunks: ['Pascal ka qanoon ye bayan karta hai...'] }),
    )

    renderChat()

    // Switch language to Roman
    const romanBtn = screen.getByText('Roman')
    fireEvent.click(romanBtn)

    // Type query and send
    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: 'Pascal ka qanoon kya hai?' } })
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      expect(askTutor).toHaveBeenCalledWith({
        message: 'Pascal ka qanoon kya hai?',
        lang: 'ur-Latn',
        session_id: null,
      })
    })
  })

  it('opens page scan preview dialog when citation is clicked', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ pages: [PAGE_155], chunks: ['See chapter 7 page 155.'] }),
    )

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
    vi.mocked(askTutor).mockImplementationOnce(() => {
      throw new Error('Network error')
    })

    renderChat()

    const input = screen.getByPlaceholderText(en.tutor.chat.inputPlaceholder)
    fireEvent.change(input, { target: { value: 'Force formula' } })
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      expect(screen.getByText(en.tutor.chat.errorFallback)).toBeInTheDocument()
      expect(screen.getByText(en.tutor.chat.retry)).toBeInTheDocument()
    })

    // Resolves on retry
    vi.mocked(askTutor).mockReturnValueOnce(streamOf({ chunks: ['F = ma'] }))

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

describe('PhysicsChatView streaming', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows citations before any of the answer text has arrived', async () => {
    // The `pages` frame resolves, then the test asserts before draining tokens.
    // That ordering is the whole user-visible benefit of streaming here:
    // retrieval takes milliseconds and generation takes seconds.
    let releaseTokens: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      releaseTokens = resolve
    })
    vi.mocked(askTutor).mockReturnValueOnce(
      (async function* () {
        yield {
          event: 'pages',
          data: {
            pages: [PAGE_155],
            retriever: 'remote',
            intent: 'retrieve',
            timings: { search: 0.01 },
          },
        }
        await gate
        yield { event: 'token', data: { text: 'A thermocouple' } }
        yield {
          event: 'done',
          data: { session_id: 'sess-1', message_id: 'm1', timings: {}, error: null },
        }
      })(),
    )

    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/A thermocouple/)).not.toBeInTheDocument()

    releaseTokens()
    await waitFor(() => {
      expect(screen.getByText(/A thermocouple/)).toBeInTheDocument()
    })
  })

  it('accumulates tokens into one answer', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ pages: [PAGE_155], chunks: ['Heat ', 'is ', 'energy ', 'in transit.'] }),
    )
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText('Heat is energy in transit.')).toBeInTheDocument()
    })
  })

  it('reuses the session id the server assigned on the next turn', async () => {
    vi.mocked(askTutor)
      .mockReturnValueOnce(streamOf({ chunks: ['first'], sessionId: 'sess-42' }))
      .mockReturnValueOnce(streamOf({ chunks: ['second'], sessionId: 'sess-42' }))

    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))
    await waitFor(() => expect(screen.getByText('first')).toBeInTheDocument())

    fireEvent.click(screen.getByText(en.tutor.chat.chip2))
    await waitFor(() => {
      expect(askTutor).toHaveBeenNthCalledWith(
        2,
        expect.objectContaining({ session_id: 'sess-42' }),
      )
    })
  })

  it('warns when the answer came from a keyword match instead of the usual search', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ pages: [PAGE_155], chunks: ['Answer.'], retriever: 'heuristic' }),
    )
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText(en.tutor.chat.degradedNotice)).toBeInTheDocument()
    })
  })

  it('does NOT warn when the keyword index answered a reference lookup', async () => {
    // ⚠️ THE DISTINCTION THAT MATTERS. "numerical 7.3" is answered from the
    // syllabus index BY DESIGN and is a perfectly good answer. Warning here
    // would train students to distrust correct answers - which is why `intent`
    // exists alongside `retriever` and must be read with it.
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({
        pages: [PAGE_155],
        chunks: ['Exercise 7.3 asks...'],
        retriever: 'heuristic',
        intent: 'reference',
      }),
    )
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText('Exercise 7.3 asks...')).toBeInTheDocument()
    })
    expect(screen.queryByText(en.tutor.chat.degradedNotice)).not.toBeInTheDocument()
  })

  it('keeps the partial answer and its citations when generation fails mid-stream', async () => {
    // After the first byte the HTTP status is already committed, so the failure
    // arrives on `done`. What did arrive is real and stays on screen.
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({
        pages: [PAGE_155],
        chunks: ['Heat is energy in '],
        error: 'MODEL_UNAVAILABLE',
      }),
    )
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText('Heat is energy in')).toBeInTheDocument()
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
      expect(screen.getByText(en.tutor.chat.retry)).toBeInTheDocument()
    })
  })

  it('falls back to the error message when the request fails before it starts', async () => {
    vi.mocked(askTutor).mockImplementationOnce(() => {
      throw new Error('503')
    })
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText(en.tutor.chat.errorFallback)).toBeInTheDocument()
    })
  })
})

describe('PhysicsChatView history', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists past conversations and resumes one', async () => {
    vi.mocked(listTutorSessions).mockResolvedValueOnce([
      {
        id: 'sess-9',
        subject: 'physics',
        class_level: 9,
        chapter: 7,
        started_at: '2026-10-12T10:00:00Z',
        message_count: 2,
        last_message_at: '2026-10-12T10:01:00Z',
        opening_question: 'how does a thermocouple work',
      },
    ])
    vi.mocked(getTutorSession).mockResolvedValueOnce({
      id: 'sess-9',
      subject: 'physics',
      class_level: 9,
      chapter: 7,
      started_at: '2026-10-12T10:00:00Z',
      ended_at: null,
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'how does a thermocouple work',
          created_at: '2026-10-12T10:00:00Z',
          pages: [],
        },
        {
          id: 'm2',
          role: 'assistant',
          content: 'Two dissimilar metals form two junctions.',
          created_at: '2026-10-12T10:00:30Z',
          pages: [PAGE_155],
        },
      ],
    })

    renderChat()
    fireEvent.click(screen.getByLabelText(en.tutor.chat.history))

    await waitFor(() => {
      expect(screen.getByText('how does a thermocouple work')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('how does a thermocouple work'))

    await waitFor(() => {
      expect(screen.getByText('Two dissimilar metals form two junctions.')).toBeInTheDocument()
      expect(screen.getByText(/Page 155/)).toBeInTheDocument()
    })
  })

  it('a resumed conversation continues the same server session', async () => {
    vi.mocked(listTutorSessions).mockResolvedValueOnce([
      {
        id: 'sess-9',
        subject: 'physics',
        class_level: 9,
        chapter: null,
        started_at: '2026-10-12T10:00:00Z',
        message_count: 1,
        last_message_at: null,
        opening_question: 'earlier question',
      },
    ])
    vi.mocked(getTutorSession).mockResolvedValueOnce({
      id: 'sess-9',
      subject: 'physics',
      class_level: 9,
      chapter: null,
      started_at: '2026-10-12T10:00:00Z',
      ended_at: null,
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'earlier question',
          created_at: '2026-10-12T10:00:00Z',
          pages: [],
        },
      ],
    })
    vi.mocked(askTutor).mockReturnValueOnce(streamOf({ chunks: ['continued'] }))

    renderChat()
    fireEvent.click(screen.getByLabelText(en.tutor.chat.history))
    await waitFor(() => expect(screen.getByText('earlier question')).toBeInTheDocument())
    fireEvent.click(screen.getByText('earlier question'))
    await waitFor(() =>
      expect(screen.queryByText(en.tutor.chat.history)).not.toBeInTheDocument(),
    )

    fireEvent.click(screen.getByText(en.tutor.chat.chip1))
    await waitFor(() => {
      expect(askTutor).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'sess-9' }))
    })
  })

  it('says so when past conversations cannot be loaded', async () => {
    vi.mocked(listTutorSessions).mockRejectedValueOnce(new Error('403'))
    renderChat()
    fireEvent.click(screen.getByLabelText(en.tutor.chat.history))
    await waitFor(() => {
      expect(screen.getByText(en.tutor.chat.historyError)).toBeInTheDocument()
    })
  })
})

describe('PhysicsChatView figures', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the cropped figure with its caption', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      (async function* () {
        yield {
          event: 'pages',
          data: {
            pages: [PAGE_155],
            retriever: 'remote',
            intent: 'retrieve',
            timings: { search: 0.01 },
          },
        }
        yield { event: 'token', data: { text: 'A thermocouple has two junctions.' } }
        yield {
          event: 'figure',
          data: {
            message_id: 'm1',
            page: 155,
            caption: 'Fig. 7.8 Thermocouple',
            url: '/api/tutor/figures/m1',
          },
        }
        yield {
          event: 'done',
          data: { session_id: 's1', message_id: 'm1', timings: {}, error: null },
        }
      })(),
    )

    vi.mocked(apiFetch).mockResolvedValueOnce(new Blob(['jpegbytes'], { type: 'image/jpeg' }))

    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      const image = screen.getByAltText('Fig. 7.8 Thermocouple')
      // ⚠️ A `data:` URI, NOT the raw route. This assertion used to read
      // `toHaveAttribute('src', '/api/tutor/figures/m1')`, which passed while the
      // image was broken for every real student: the route is authenticated and an
      // `<img>` sends no bearer token, so the browser got a 401. Asserting the URL
      // was well-formed could never catch that; asserting bytes arrived does.
      // `blob:` is absent from the CSP's `img-src 'self' data:`, hence data:.
      expect(image.getAttribute('src')).toMatch(/^data:image\/jpeg/)
      expect(apiFetch).toHaveBeenCalledWith('/tutor/figures/m1', { responseType: 'blob' })
      expect(screen.getByText('Fig. 7.8 Thermocouple')).toBeInTheDocument()
    })
  })

  it('shows no figure when the answer had none', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf({ pages: [PAGE_155], chunks: ['No diagram needed.'] }),
    )
    renderChat()
    fireEvent.click(screen.getByText(en.tutor.chat.chip1))

    await waitFor(() => {
      expect(screen.getByText('No diagram needed.')).toBeInTheDocument()
    })
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
