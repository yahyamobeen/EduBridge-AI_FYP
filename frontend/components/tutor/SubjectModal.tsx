'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { ArrowLeftIcon, CloseIcon, HistoryIcon } from '@/components/ui/Icon'
import { listTutorBooks } from '@/lib/api/endpoints'
import type { TutorBook, TutorBooksResponse } from '@/lib/api/types'
import { PhysicsChatView } from './PhysicsChatView'
import { type OpenBook, SubjectIcon, subjectLabel } from './subjects'

type Props = {
  isOpen: boolean
  onClose: () => void
}

/**
 * The tutor: the student's subjects, then a chat with the chosen book.
 *
 * The subjects come from `GET /api/tutor/books` - the student's own board, class and
 * group (tdd.md §3.2a "Many books") - so this component holds no list of its own. The
 * body mounts on every open, which re-reads the list and starts on the subject screen.
 */
export function SubjectModal({ isOpen, onClose }: Props) {
  if (!isOpen) return null
  return <TutorModalBody onClose={onClose} />
}

type Books =
  { status: 'loading' } | { status: 'error' } | { status: 'ready'; data: TutorBooksResponse }

type Stage =
  | { kind: 'select' }
  | { kind: 'coming-soon'; subject: string }
  | { kind: 'chat'; book: OpenBook }

function TutorModalBody({ onClose }: { onClose: () => void }) {
  const tModal = useTranslations('tutor.modal')
  const tSubs = useTranslations('tutor.subjects')
  const tBoards = useTranslations('tutor.boards')
  const [books, setBooks] = useState<Books>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)
  const [stage, setStage] = useState<Stage>({ kind: 'select' })

  useEffect(() => {
    let active = true
    listTutorBooks()
      .then((data) => {
        if (active) setBooks({ status: 'ready', data })
      })
      .catch(() => {
        if (active) setBooks({ status: 'error' })
      })
    return () => {
      active = false
    }
  }, [reloadKey])

  function retry() {
    setBooks({ status: 'loading' })
    setReloadKey((k) => k + 1)
  }

  function choose(entry: TutorBook, data: TutorBooksResponse) {
    if (entry.available && entry.book_id) {
      setStage({
        kind: 'chat',
        book: {
          bookId: entry.book_id,
          subject: entry.subject,
          board: data.board,
          classLevel: data.class_level,
        },
      })
    } else {
      setStage({ kind: 'coming-soon', subject: entry.subject })
    }
  }

  const closeButton = (
    <button
      type="button"
      onClick={onClose}
      aria-label={tModal('close')}
      className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
    >
      <CloseIcon className="h-5 w-5" />
    </button>
  )

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tutor-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div className="relative w-full max-w-2xl">
        {stage.kind === 'chat' ? (
          <PhysicsChatView
            book={stage.book}
            onBack={() => setStage({ kind: 'select' })}
            onClose={onClose}
          />
        ) : stage.kind === 'coming-soon' ? (
          <div className="overflow-hidden rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-6 shadow-2xl sm:p-8">
            <div className="flex items-center justify-between">
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-fixed text-primary">
                <HistoryIcon className="h-6 w-6" />
              </span>
              {closeButton}
            </div>

            <div className="mt-4 space-y-2 text-start">
              <h3
                id="tutor-modal-title"
                className="text-headline-sm font-headline font-bold text-on-surface"
              >
                {tModal('comingSoonTitle')}
              </h3>
              <p className="text-body-md text-on-surface-variant">
                {tModal('comingSoonNotice', { subject: subjectLabel(stage.subject, tSubs) })}
              </p>
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => setStage({ kind: 'select' })}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-container"
              >
                <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
                <span>{tModal('back')}</span>
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-outline px-5 py-2.5 text-body-md font-semibold text-on-surface transition-colors hover:bg-surface-container-high"
              >
                {tModal('close')}
              </button>
            </div>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-6 shadow-2xl sm:p-8">
            <div className="flex items-start justify-between">
              <div className="space-y-1 text-start">
                <h3
                  id="tutor-modal-title"
                  className="font-headline text-headline-md font-bold text-on-surface"
                >
                  {books.status === 'ready'
                    ? tModal('title', { class: books.data.class_level })
                    : tModal('loadingTitle')}
                </h3>
                {books.status === 'ready' && (
                  <p className="text-body-sm text-on-surface-variant">
                    {tModal('subtitle', { board: tBoards(books.data.board) })}
                  </p>
                )}
              </div>
              {closeButton}
            </div>

            {books.status === 'loading' ? (
              <div
                aria-busy="true"
                className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4"
              >
                <p className="sr-only" role="status">
                  {tModal('loading')}
                </p>
                {Array.from({ length: 6 }, (_, i) => (
                  <div
                    key={i}
                    className="h-[74px] animate-pulse rounded-xl border border-outline-variant/30 bg-surface-container-low"
                  />
                ))}
              </div>
            ) : books.status === 'error' ? (
              <div role="alert" className="mt-6 space-y-3 text-start">
                <p className="text-body-md text-on-surface-variant">{tModal('loadError')}</p>
                <button
                  type="button"
                  onClick={retry}
                  className="rounded-lg bg-primary px-5 py-2.5 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary-container"
                >
                  {tModal('retry')}
                </button>
              </div>
            ) : books.data.books.length === 0 ? (
              <p className="mt-6 text-start text-body-md text-on-surface-variant">
                {tModal('empty')}
              </p>
            ) : (
              <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
                {[
                  ...books.data.books.filter((b) => b.available),
                  ...books.data.books.filter((b) => !b.available),
                ].map((entry) => {
                  return (
                    <button
                      key={entry.subject}
                      type="button"
                      onClick={() => choose(entry, books.data)}
                      className={`group relative flex items-center justify-between rounded-xl border p-4 text-start transition-all hover:scale-[1.01] hover:shadow-md ${
                        entry.available
                          ? 'border-primary/40 bg-surface-container-low hover:border-primary'
                          : 'border-outline-variant/40 bg-surface-container-lowest hover:border-outline'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={`flex h-10 w-10 items-center justify-center rounded-lg shadow-sm ${
                            entry.available
                              ? 'bg-primary-container text-on-primary'
                              : 'bg-surface-container-high text-on-surface'
                          }`}
                        >
                          <SubjectIcon subject={entry.subject} className="h-5 w-5" />
                        </span>
                        <div>
                          <p className="text-title-md font-headline font-semibold text-on-surface">
                            {subjectLabel(entry.subject, tSubs)}
                          </p>
                          <p className="text-xs text-on-surface-variant">
                            {tModal('subjectMeta', {
                              board: books.data.board,
                              class: books.data.class_level,
                            })}
                          </p>
                        </div>
                      </div>

                      <span
                        className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          entry.available
                            ? 'bg-primary-container text-on-primary'
                            : 'bg-surface-variant text-on-surface-variant'
                        }`}
                      >
                        {entry.available ? tModal('availableBadge') : tModal('comingSoonBadge')}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
