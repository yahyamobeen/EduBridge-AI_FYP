import { fireEvent, render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { PhysicsChatView } from './PhysicsChatView'
import { SubjectModal } from './SubjectModal'

vi.mock('@/lib/api/endpoints', () => ({
  askTutor: vi.fn(),
  listTutorSessions: vi.fn(),
  getTutorSession: vi.fn(),
  speakText: vi.fn(),
  transcribeAudio: vi.fn(),
  listTutorBooks: vi.fn().mockResolvedValue({
    board: 'STBB',
    class_level: 10,
    books: [
      { book_id: 'Sindh_10_Chemistry', subject: 'Chemistry', available: true },
      { book_id: 'Sindh_9_English', subject: 'English', available: true },
      { book_id: null, subject: 'Biology', available: false },
      { book_id: null, subject: 'Computer Science', available: false },
      { book_id: null, subject: 'Mathematics', available: false },
      { book_id: null, subject: 'Physics', available: false },
      { book_id: null, subject: 'Urdu', available: false },
      { book_id: null, subject: 'Islamiat', available: false },
      { book_id: null, subject: 'Pakistan Studies', available: false },
      { book_id: null, subject: 'Quran Translation', available: false },
    ],
  }),
  tutorPagePath: (bookId: string, page: number) => `/tutor/books/${bookId}/pages/${page}`,
}))

type Messages = typeof en

// The house pattern (`Landing.test.tsx`): next-intl reports a missing key or a broken
// placeholder through onError rather than throwing, so an untranslated tutor string
// would otherwise pass silently. Every subject the catalogue can send is listed above,
// so every `tutor.subjects` key the picker needs is exercised.
describe.each([
  ['en', en],
  ['ur', ur],
  ['ur-Latn', urLatn],
])('the tutor renders fully in %s', (locale, messages) => {
  it('subject picker: no missing keys', async () => {
    const onError = vi.fn()
    render(
      <NextIntlClientProvider locale={locale} messages={messages as Messages} onError={onError}>
        <SubjectModal isOpen onClose={vi.fn()} />
      </NextIntlClientProvider>,
    )
    const m = messages as Messages
    expect(await screen.findByText(m.tutor.subjects.pakistanStudies)).toBeInTheDocument()
    expect(screen.getByText(m.tutor.subjects.quranTranslation)).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalled()
  })

  it('chat: no missing keys', () => {
    const onError = vi.fn()
    render(
      <NextIntlClientProvider locale={locale} messages={messages as Messages} onError={onError}>
        <PhysicsChatView
          book={{
            bookId: 'Sindh_9_English',
            subject: 'English',
            board: 'STBB',
            classLevel: 10,
          }}
          onBack={vi.fn()}
          onClose={vi.fn()}
        />
      </NextIntlClientProvider>,
    )
    fireEvent.click(screen.getByLabelText((messages as Messages).tutor.chat.history))
    expect(onError).not.toHaveBeenCalled()
  })
})
