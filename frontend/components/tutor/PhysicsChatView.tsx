'use client'

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useTranslations } from 'next-intl'
import {
  ArrowLeftIcon,
  AtomIcon,
  BookIcon,
  CloseIcon,
  HistoryIcon,
  SendIcon,
  SparkIcon,
} from '@/components/ui/Icon'
import { askTutor, getTutorSession, listTutorSessions } from '@/lib/api/endpoints'
import { TutorFigure } from './TutorFigure'
import { TutorMarkdown } from './TutorMarkdown'
import type {
  PageCitation,
  PhysicsChatMessage,
  RetrieverTier,
  TurnIntent,
  TutorDoneEvent,
  TutorFigureEvent,
  TutorPagesEvent,
  TutorSessionSummary,
  TutorTokenEvent,
} from '@/lib/api/types'

type Props = {
  onBack: () => void
  onClose: () => void
}

type MessageWithCitations = PhysicsChatMessage & {
  pages?: PageCitation[]
  error?: boolean
  /** Which tier produced the citations, and why. Read together, never alone. */
  retriever?: RetrieverTier
  intent?: TurnIntent
  /** True while tokens are still arriving, so the caret can show. */
  streaming?: boolean
  /** The cropped figure, when the generator pointed at one. */
  figure?: { messageId: string; caption: string; page: number }
}

/**
 * Should the answer be marked as degraded?
 *
 * ⚠️ `retriever === 'heuristic'` ALONE IS NOT THE TEST, and getting this wrong
 * in either direction is bad. A reference lookup ("numerical 7.3") answers from
 * the keyword index BY DESIGN and is perfectly good; the same tier reached for a
 * normal question means the retrieval service was unreachable and the student is
 * reading a keyword match. Only the second deserves a warning.
 */
function isDegraded(msg: MessageWithCitations): boolean {
  return msg.retriever === 'heuristic' && msg.intent !== 'reference'
}

export function PhysicsChatView({ onBack, onClose }: Props) {
  const t = useTranslations('tutor.chat')
  const [lang, setLang] = useState<'en' | 'ur-Latn' | 'ur'>('en')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<MessageWithCitations[]>([])
  const [previewPage, setPreviewPage] = useState<number | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  /**
   * The server-assigned session. Held in a ref rather than state because it is
   * read inside the streaming loop and never rendered - as state, the loop
   * would close over a stale value on the turn that creates it.
   */
  const sessionIdRef = useRef<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [sessions, setSessions] = useState<TutorSessionSummary[] | null>(null)
  const [historyError, setHistoryError] = useState(false)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, loading])

  const quickChips = [t('chip1'), t('chip2'), t('chip3'), t('chip4')]

  async function handleSend(textToSend?: string) {
    const query = (textToSend ?? input).trim()
    if (!query || loading) return

    setInput('')
    const userMsg: MessageWithCitations = { role: 'user', content: query }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setLoading(true)

    // No `history` is sent. The server reads the transcript it stored, and
    // trusting a client-supplied one would let this component put words in the
    // assistant's mouth and have the model treat them as its own prior answer.
    try {
      let started = false

      for await (const { event, data } of askTutor({
        message: query,
        lang,
        session_id: sessionIdRef.current,
      })) {
        if (event === 'pages') {
          // Citations arrive BEFORE the first token. Appending the assistant
          // bubble here is what makes the wait legible: the student can see
          // which pages were found while the prose is still being written.
          const frame = data as TutorPagesEvent
          started = true
          setLoading(false)
          setMessages([
            ...updatedMessages,
            {
              role: 'assistant',
              content: '',
              pages: frame.pages,
              retriever: frame.retriever,
              intent: frame.intent,
              streaming: true,
            },
          ])
        } else if (event === 'token') {
          const { text } = data as TutorTokenEvent
          // Append to the LAST message only, rebuilding from `updatedMessages`
          // each time, so a re-render mid-stream cannot duplicate the turn.
          setMessages((current) => {
            const next = [...current]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { ...last, content: last.content + text }
            }
            return next
          })
        } else if (event === 'figure') {
          const frame = data as TutorFigureEvent
          setMessages((current) => {
            const next = [...current]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                figure: {
                  messageId: frame.message_id,
                  caption: frame.caption,
                  page: frame.page,
                },
              }
            }
            return next
          })
        } else if (event === 'done') {
          const frame = data as TutorDoneEvent
          sessionIdRef.current = frame.session_id
          setMessages((current) => {
            const next = [...current]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                streaming: false,
                // A failure AFTER the first byte cannot change the HTTP status,
                // so it arrives here. The citations and partial text stay on
                // screen - they are real - and the turn is marked so the
                // student is not left thinking the answer finished.
                ...(frame.error ? { error: true } : {}),
              }
            }
            return next
          })
        }
      }

      if (!started) {
        // The stream opened and closed without a `pages` frame. Nothing to show.
        setMessages([
          ...updatedMessages,
          { role: 'assistant', content: t('errorFallback'), error: true },
        ])
      }
    } catch {
      // A failure BEFORE the first byte: an ordinary error response, so the
      // whole turn failed and nothing partial is on screen.
      setMessages([
        ...updatedMessages,
        { role: 'assistant', content: t('errorFallback'), error: true },
      ])
    } finally {
      // `finally`, not `catch`: this screen stays mounted after a send, so
      // re-enabling the control is correct here (frontend/CLAUDE.md §3).
      setLoading(false)
    }
  }

  async function openHistory() {
    setShowHistory(true)
    setHistoryError(false)
    try {
      setSessions(await listTutorSessions(20))
    } catch {
      setHistoryError(true)
    }
  }

  async function loadSession(id: string) {
    setShowHistory(false)
    setLoading(true)
    try {
      const detail = await getTutorSession(id)
      sessionIdRef.current = detail.id
      setMessages(
        detail.messages
          // `system` turns are not part of the conversation a student had.
          .filter((m) => m.role !== 'system')
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            pages: m.pages,
          })),
      )
    } catch {
      // ⚠️ A 403 here means "not available", NOT "signed out": a session that is
      // not yours and one that does not exist answer identically, so that an id
      // cannot be probed for existence.
      setHistoryError(true)
      setShowHistory(true)
    } finally {
      setLoading(false)
    }
  }

  function startNewChat() {
    sessionIdRef.current = null
    setMessages([])
    setShowHistory(false)
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    handleSend()
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-[80vh] max-h-[750px] w-full flex-col overflow-hidden rounded-xl bg-surface-container-lowest shadow-2xl">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-outline-variant/30 bg-surface-container-low px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            aria-label="Back"
            className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
          >
            <ArrowLeftIcon className="h-5 w-5 rtl:-scale-x-100" />
          </button>
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-container text-on-primary">
              <AtomIcon className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-title-md font-headline font-bold text-on-surface">
                {t('title')}
              </h2>
              <p className="text-body-sm text-on-surface-variant">{t('subtitle')}</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={showHistory ? () => setShowHistory(false) : openHistory}
            aria-label={t('history')}
            aria-expanded={showHistory}
            className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
          >
            <HistoryIcon className="h-5 w-5" />
          </button>

          {/* Language selector */}
          <div className="flex rounded-lg border border-outline-variant/40 bg-surface p-0.5 text-body-sm font-semibold">
            <button
              type="button"
              onClick={() => setLang('en')}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                lang === 'en'
                  ? 'bg-primary text-on-primary shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              EN
            </button>
            <button
              type="button"
              onClick={() => setLang('ur-Latn')}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                lang === 'ur-Latn'
                  ? 'bg-primary text-on-primary shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              Roman
            </button>
            <button
              type="button"
              onClick={() => setLang('ur')}
              className={`rounded-md px-2.5 py-1 font-urdu text-xs transition-colors ${
                lang === 'ur'
                  ? 'bg-primary text-on-primary shadow-sm'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              اردو
            </button>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-variant"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
      </header>

      {/* Messages Scroll Area */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
        {/* Welcome message */}
        <div className="rounded-xl border border-secondary/20 bg-secondary-container/20 p-4 text-start">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container">
              <SparkIcon className="h-4 w-4" />
            </span>
            <div className="space-y-2">
              <p className="text-body-md text-on-surface">{t('welcome')}</p>
              <div className="flex flex-wrap gap-2 pt-1">
                {quickChips.map((chip, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSend(chip)}
                    className="rounded-full border border-outline-variant/60 bg-surface px-3 py-1 text-xs font-medium text-primary transition-colors hover:border-primary hover:bg-primary-container/10"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Past conversations */}
        {showHistory && (
          <section
            aria-label={t('history')}
            className="rounded-xl border border-outline-variant/40 bg-surface-container p-3"
          >
            <div className="flex items-center justify-between">
              <p className="text-body-sm font-semibold text-on-surface">{t('history')}</p>
              <button
                type="button"
                onClick={startNewChat}
                className="text-xs font-semibold text-primary underline hover:opacity-80"
              >
                {t('newChat')}
              </button>
            </div>

            {historyError ? (
              <p className="mt-2 text-body-sm text-on-surface-variant">{t('historyError')}</p>
            ) : sessions === null ? (
              <p className="mt-2 text-body-sm text-on-surface-variant">{t('thinking')}</p>
            ) : sessions.length === 0 ? (
              <p className="mt-2 text-body-sm text-on-surface-variant">{t('historyEmpty')}</p>
            ) : (
              <ul className="mt-2 flex flex-col gap-1">
                {sessions.map((session) => (
                  <li key={session.id}>
                    <button
                      type="button"
                      onClick={() => loadSession(session.id)}
                      className="flex w-full flex-col items-start rounded-lg px-2 py-1.5 text-start transition-colors hover:bg-surface-variant"
                    >
                      <span className="line-clamp-1 text-body-sm text-on-surface">
                        {session.opening_question ?? t('history')}
                      </span>
                      <span className="text-xs text-on-surface-variant">
                        {session.chapter !== null && `${t('chapter')} ${session.chapter} · `}
                        {new Date(session.started_at).toLocaleDateString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* Message bubbles */}
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
          >
            <div
              className={`rounded-2xl px-4 py-3 text-body-md shadow-sm sm:max-w-[80%] ${
                msg.role === 'user'
                  ? 'rounded-te-sm bg-primary text-on-primary'
                  : msg.error
                    ? 'rounded-ts-sm border border-error/40 bg-error-container text-on-error-container'
                    : 'rounded-ts-sm border border-outline-variant/30 bg-surface-container-high text-on-surface'
              }`}
            >
              <div
                className={msg.role === 'assistant' && !msg.error ? '' : 'whitespace-pre-wrap'}
              >
                {/*
                  Markdown and LaTeX for the tutor's own answers only. A student's
                  message is their typed input and stays plain text — see
                  TutorMarkdown's header for why that boundary is deliberate.
                */}
                {msg.role === 'assistant' && !msg.error ? (
                  <TutorMarkdown content={msg.content} />
                ) : (
                  msg.content
                )}
                {msg.streaming && (
                  <span
                    aria-hidden="true"
                    className="ms-0.5 inline-block w-[2px] animate-pulse bg-current align-middle"
                    style={{ height: '1em' }}
                  />
                )}
              </div>

              {/*
                A keyword match presented as a textbook answer is the failure
                this notice exists to prevent. Shown only when the tier is
                `heuristic` for a reason OTHER than a reference lookup - see
                `isDegraded`.
              */}
              {isDegraded(msg) && (
                <p className="mt-2 flex items-start gap-1.5 rounded-md bg-surface-container px-2 py-1.5 text-xs text-on-surface-variant">
                  <SparkIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{t('degradedNotice')}</span>
                </p>
              )}

              {msg.error && (
                <div className="mt-2 flex items-center">
                  <button
                    type="button"
                    onClick={() => {
                      const lastUserMsg = [...messages].reverse().find((m) => m.role === 'user')
                      if (lastUserMsg) handleSend(lastUserMsg.content)
                    }}
                    className="inline-flex items-center gap-1 text-xs font-semibold underline hover:opacity-80"
                  >
                    {t('retry')}
                  </button>
                </div>
              )}

              {/*
                The cropped figure. Same-origin by necessity: the CSP is
                `img-src 'self' data:`, so an external URL here is blocked.
              */}
              {msg.figure && (
                <TutorFigure
                  messageId={msg.figure.messageId}
                  alt={msg.figure.caption || `${t('page')} ${msg.figure.page}`}
                  caption={msg.figure.caption}
                />
              )}

              {/* Citations Preview Chips */}
              {msg.pages && msg.pages.length > 0 && (
                <div className="mt-3 border-t border-outline-variant/30 pt-2">
                  <p className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
                    <BookIcon className="h-3.5 w-3.5" />
                    {t('references')}:
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-2">
                    {msg.pages.map((p) => (
                      <button
                        key={p.page}
                        type="button"
                        onClick={() => setPreviewPage(p.page)}
                        className="inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-surface px-2.5 py-1 text-xs font-semibold text-primary transition-colors hover:bg-primary hover:text-on-primary"
                      >
                        <span>
                          {t('page')} {p.page}
                        </span>
                        {p.chapter && (
                          <span className="text-on-surface-variant">
                            ({t('chapter')} {p.chapter})
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Loading / Thinking bubble */}
        {loading && (
          <div className="flex items-start">
            <div className="rounded-ts-sm flex items-center gap-2 rounded-2xl border border-outline-variant/30 bg-surface-container-high px-4 py-3 text-body-sm text-on-surface-variant shadow-sm">
              <span className="h-2 w-2 animate-ping rounded-full bg-primary" />
              <span>{t('thinking')}</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Form Footer */}
      <footer className="border-t border-outline-variant/30 bg-surface-container-low p-3 sm:p-4">
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
            placeholder={t('inputPlaceholder')}
            className="flex-1 rounded-lg border border-outline bg-surface px-4 py-2.5 text-body-md text-on-surface placeholder:text-on-surface-variant/60 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            aria-label={t('send')}
            className="inline-flex h-11 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2.5 font-semibold text-on-primary transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span>{t('send')}</span>
            <SendIcon className="h-4 w-4 rtl:-scale-x-100" />
          </button>
        </form>
        <p className="mt-2 text-center text-xs text-on-surface-variant">{t('disclaimer')}</p>
      </footer>

      {/* Page Zoom Preview Modal */}
      {previewPage && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        >
          <div className="relative max-h-[90vh] max-w-2xl overflow-hidden rounded-xl bg-surface-container-lowest p-2 shadow-2xl">
            <div className="flex items-center justify-between border-b border-outline-variant/30 px-3 py-2">
              <h3 className="text-title-sm font-headline font-bold text-on-surface">
                {t('page')} {previewPage} (PCTB Physics 9)
              </h3>
              <button
                type="button"
                onClick={() => setPreviewPage(null)}
                aria-label="Close"
                className="flex h-7 w-7 items-center justify-center rounded-full hover:bg-surface-variant"
              >
                <CloseIcon className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[75vh] overflow-y-auto p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/tutor/class9/physics/pages/${previewPage}`}
                alt={`Textbook Page ${previewPage}`}
                className="mx-auto h-auto max-w-full rounded shadow"
                onError={(e) => {
                  ;(e.target as HTMLElement).style.display = 'none'
                }}
              />
              <p className="mt-2 text-center text-xs text-on-surface-variant">
                Punjab Textbook Board (PCTB) Class 9 Physics Official Scan
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
