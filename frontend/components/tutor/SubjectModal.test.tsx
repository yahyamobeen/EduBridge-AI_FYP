import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import type { TutorBooksResponse } from '@/lib/api/types'
import { SubjectModal } from './SubjectModal'

vi.mock('@/lib/api/endpoints', () => ({
  askTutor: vi.fn(),
  listTutorBooks: vi.fn(),
  listTutorSessions: vi.fn(),
  getTutorSession: vi.fn(),
  tutorPagePath: (bookId: string, page: number) => `/tutor/books/${bookId}/pages/${page}`,
}))

import { askTutor, listTutorBooks } from '@/lib/api/endpoints'

/** A Sindh Class 10 science student: what GET /api/tutor/books returns for them. */
const STBB_10: TutorBooksResponse = {
  board: 'STBB',
  class_level: 10,
  books: [
    { book_id: null, subject: 'Biology', available: false },
    { book_id: 'Sindh_10_Chemistry', subject: 'Chemistry', available: true },
    { book_id: 'Sindh_9_English', subject: 'English', available: true },
    { book_id: null, subject: 'Quran Translation', available: false },
  ],
}

const PCTB_9: TutorBooksResponse = {
  board: 'PCTB',
  class_level: 9,
  books: [{ book_id: 'Punjab_9_Physics', subject: 'Physics', available: true }],
}

/** The frame sequence the chat view consumes: pages, tokens, done. */
function streamOf(reply: string, pages: unknown[] = []) {
  return (async function* () {
    yield {
      event: 'pages',
      data: { pages, retriever: 'remote', intent: 'retrieve', timings: { search: 0.01 } },
    }
    yield { event: 'token', data: { text: reply } }
    yield {
      event: 'done',
      data: { session_id: 'sess-1', message_id: 'm1', timings: {}, error: null },
    }
  })()
}

function fill(template: string, values: Record<string, string | number>) {
  return Object.entries(values).reduce(
    (s, [k, v]) => s.replaceAll(`{${k}}`, String(v)),
    template,
  )
}

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
    vi.mocked(listTutorBooks).mockResolvedValue(STBB_10)
  })

  it('renders nothing when closed, and fetches nothing', () => {
    renderModal({ isOpen: false })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(listTutorBooks).not.toHaveBeenCalled()
  })

  it("lists the student's own subjects, available first, with board and class", async () => {
    renderModal()

    expect(
      await screen.findByText(fill(en.tutor.modal.title, { class: 10 })),
    ).toBeInTheDocument()
    expect(
      screen.getByText(fill(en.tutor.modal.subtitle, { board: en.tutor.boards.STBB })),
    ).toBeInTheDocument()

    const tiles = screen.getAllByRole('button').filter((b) => b.textContent?.includes('STBB'))
    expect(tiles.map((t) => t.querySelector('p')?.textContent)).toEqual([
      en.tutor.subjects.chemistry,
      en.tutor.subjects.english,
      en.tutor.subjects.biology,
      en.tutor.subjects.quranTranslation,
    ])
    expect(screen.getAllByText(en.tutor.modal.availableBadge)).toHaveLength(2)
    expect(screen.getAllByText(en.tutor.modal.comingSoonBadge)).toHaveLength(2)
    expect(
      screen.getAllByText(fill(en.tutor.modal.subjectMeta, { board: 'STBB', class: 10 })),
    ).toHaveLength(4)
  })

  it('shows a loading state, then an error with a working retry', async () => {
    vi.mocked(listTutorBooks).mockRejectedValueOnce(new Error('offline'))
    renderModal()

    expect(screen.getByRole('status')).toHaveTextContent(en.tutor.modal.loading)
    expect(await screen.findByText(en.tutor.modal.loadError)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: en.tutor.modal.retry }))
    expect(await screen.findByText(en.tutor.subjects.chemistry)).toBeInTheDocument()
    expect(listTutorBooks).toHaveBeenCalledTimes(2)
  })

  it('a subject without a book shows the coming-soon notice, and Back returns', async () => {
    renderModal()
    fireEvent.click((await screen.findByText(en.tutor.subjects.biology)).closest('button')!)

    expect(screen.getByText(en.tutor.modal.comingSoonTitle)).toBeInTheDocument()
    expect(
      screen.getByText(
        fill(en.tutor.modal.comingSoonNotice, { subject: en.tutor.subjects.biology }),
      ),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByText(en.tutor.modal.back).closest('button')!)
    expect(
      await screen.findByText(fill(en.tutor.modal.title, { class: 10 })),
    ).toBeInTheDocument()
  })

  it('Tarjuma-tul-Quran is listed but not openable (prd.md FR-17)', async () => {
    renderModal()
    fireEvent.click(
      (await screen.findByText(en.tutor.subjects.quranTranslation)).closest('button')!,
    )
    expect(screen.getByText(en.tutor.modal.comingSoonTitle)).toBeInTheDocument()
  })

  it('an available subject opens the chat for that book, with no Physics chips', async () => {
    renderModal()
    fireEvent.click((await screen.findByText(en.tutor.subjects.chemistry)).closest('button')!)

    const subject = en.tutor.subjects.chemistry
    expect(screen.getByText(fill(en.tutor.chat.title, { subject }))).toBeInTheDocument()
    expect(
      screen.getByText(fill(en.tutor.chat.subtitle, { board: 'STBB', class: 10, subject })),
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(fill(en.tutor.chat.inputPlaceholder, { subject })),
    ).toBeInTheDocument()
    expect(screen.queryByText(en.tutor.chat.chip1)).not.toBeInTheDocument()
  })

  it('the Physics 9 book keeps its quick-prompt chips', async () => {
    vi.mocked(listTutorBooks).mockResolvedValue(PCTB_9)
    renderModal()
    fireEvent.click((await screen.findByText(en.tutor.subjects.physics)).closest('button')!)
    expect(screen.getByText(en.tutor.chat.chip1)).toBeInTheDocument()
  })

  it('sends the book with every question and renders the citations', async () => {
    vi.mocked(askTutor).mockReturnValueOnce(
      streamOf('A salt is an ionic compound.', [
        {
          page: 26,
          chapter: null,
          score: 9.3,
          url: '/api/tutor/books/Sindh_10_Chemistry/pages/26',
        },
      ]),
    )
    renderModal()
    fireEvent.click((await screen.findByText(en.tutor.subjects.chemistry)).closest('button')!)

    const subject = en.tutor.subjects.chemistry
    fireEvent.change(
      screen.getByPlaceholderText(fill(en.tutor.chat.inputPlaceholder, { subject })),
      {
        target: { value: 'What is a salt?' },
      },
    )
    fireEvent.click(screen.getByLabelText(en.tutor.chat.send))

    await waitFor(() => {
      // No `history`: the server reads the transcript it stored (tdd.md §3.2).
      expect(askTutor).toHaveBeenCalledWith({
        message: 'What is a salt?',
        lang: 'en',
        session_id: null,
        book_id: 'Sindh_10_Chemistry',
      })
    })
    expect(await screen.findByText('A salt is an ionic compound.')).toBeInTheDocument()
    expect(screen.getByText(/Page 26/)).toBeInTheDocument()
  })

  it('invokes onClose when the close button is clicked', async () => {
    const { onClose } = renderModal()
    await screen.findByText(en.tutor.subjects.chemistry)
    fireEvent.click(screen.getByLabelText(en.tutor.modal.close))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
