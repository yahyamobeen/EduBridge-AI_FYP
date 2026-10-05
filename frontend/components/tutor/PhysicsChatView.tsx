'use client'

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useTranslations } from 'next-intl'
import {
  ArrowLeftIcon,
  AtomIcon,
  BookIcon,
  CloseIcon,
  SendIcon,
  SparkIcon,
} from '@/components/ui/Icon'
import { chatClass9Physics } from '@/lib/api/endpoints'
import type { PageCitation, PhysicsChatMessage } from '@/lib/api/types'

type Props = {
  onBack: () => void
  onClose: () => void
}

type MessageWithCitations = PhysicsChatMessage & {
  pages?: PageCitation[]
  error?: boolean
}

export function PhysicsChatView({ onBack, onClose }: Props) {
  const t = useTranslations('tutor.chat')
  const [lang, setLang] = useState<'en' | 'ur-Latn' | 'ur'>('en')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<MessageWithCitations[]>([])
  const [previewPage, setPreviewPage] = useState<number | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

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

    try {
      const historyPayload = updatedMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }))

      const response = await chatClass9Physics({
        message: query,
        lang,
        history: historyPayload,
      })

      const botMsg: MessageWithCitations = {
        role: 'assistant',
        content: response.reply,
        pages: response.pages,
      }
      setMessages([...updatedMessages, botMsg])
    } catch {
      const errorMsg: MessageWithCitations = {
        role: 'assistant',
        content: t('errorFallback'),
        error: true,
      }
      setMessages([...updatedMessages, errorMsg])
    } finally {
      setLoading(false)
    }
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
              <div className="whitespace-pre-wrap">{msg.content}</div>

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
