'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ChatIcon, LockIcon } from '@/components/ui/Icon'
import { deleteMessage, getPeople, postMessage, updateSpace } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { ChatMessage, PeopleResponse, SpaceDetail } from '@/lib/api/types'
import { ConfirmInline } from './ConfirmInline'
import { CARD, CARD_HEADING, FIELD, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'
import { useChatPoll } from './useChatPoll'

/**
 * The class chat (prd.md CL-5, tdd.md §3.6, classroom Phase 7).
 *
 * CLASS-PUBLIC, and it says so: every message is visible to the whole class.
 * Who may post is decided by the DATABASE (the `space_message` insert policy);
 * this screen only explains a refusal — muted, locked or archived.
 *
 * ⚠️ THE TEACHER BADGE COMES FROM `people.owner.user_id`, NEVER FROM A NAME. A
 *    student may call themselves "Sir Ahmed"; only the owner's id earns the
 *    badge. Names come from the roster (`GET /spaces/{id}/people`), the one
 *    place the database releases them; an author it no longer lists refreshes
 *    it once and is then a "former member".
 *
 * Bodies are rendered as plain text — never HTML, never auto-linked.
 */
export function ChatTab({
  spaceId,
  isOwner,
  archived,
  onSpaceChange,
}: {
  spaceId: string
  isOwner: boolean
  archived: boolean
  onSpaceChange: (space: SpaceDetail) => void
}) {
  const t = useTranslations('classroom.chat')
  const tp = useTranslations('classroom.people')
  const format = useFormatter()
  const chat = useChatPoll(spaceId, { isOwner })
  const { messages, status, patchStatus } = chat

  // ── names ──
  const [people, setPeople] = useState<PeopleResponse | null>(null)
  const tried = useRef(new Set<string>())
  const loadPeople = useCallback(
    () =>
      getPeople(spaceId)
        .then(setPeople)
        .catch(() => {
          // Names are a nicety: the messages still show without them.
        }),
    [spaceId],
  )
  useEffect(() => {
    void loadPeople()
  }, [loadPeople])

  const names = useMemo(() => {
    const map = new Map<string, string>()
    if (!people) return map
    map.set(people.owner.user_id, people.owner.full_name ?? tp('unnamed'))
    for (const m of people.members) map.set(m.user_id, m.full_name ?? tp('unnamed'))
    return map
  }, [people, tp])

  useEffect(() => {
    if (!people) return
    const unknown = messages
      .map((m) => m.author_id)
      .filter((id) => !names.has(id) && !tried.current.has(id))
    if (unknown.length === 0) return
    for (const id of unknown) tried.current.add(id)
    void loadPeople()
  }, [people, names, messages, loadPeople])

  const ownerId = people?.owner.user_id ?? null
  const nameOf = (id: string) => names.get(id) ?? (people ? t('formerMember') : '')

  // ── keep the newest message in view, unless the reader scrolled up ──
  const list = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    const el = list.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [messages])

  // ── why posting is off ──
  const [archivedSeen, setArchivedSeen] = useState(false)
  const isArchived = archived || archivedSeen
  const notice = !status
    ? null
    : isArchived
      ? t('archived')
      : !isOwner && status.muted
        ? t('muted')
        : status.locked
          ? isOwner
            ? t('lockedOwner')
            : t('locked')
          : null
  const canPost = !!status?.canPost && !isArchived

  return (
    <section aria-labelledby="chat-heading" className={CARD}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 id="chat-heading" className={CARD_HEADING}>
          <ChatIcon className="h-5 w-5" />
          {t('heading')}
        </h2>
        {isOwner && !isArchived && status && (
          <LockToggle
            spaceId={spaceId}
            locked={status.locked}
            onChange={(space) => {
              patchStatus({ locked: space.chat_locked })
              onSpaceChange(space)
            }}
          />
        )}
      </div>
      <p className="mb-4 text-body-sm text-on-surface-variant">{t('intro')}</p>

      {chat.failed ? (
        <FormBanner>{t('unavailable')}</FormBanner>
      ) : !status ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : (
        <>
          <div
            ref={list}
            onScroll={(e) => {
              const el = e.currentTarget
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
            }}
            className="max-h-[28rem] overflow-y-auto"
          >
            {chat.olderCursor && (
              <div className="mb-3 text-center">
                <button
                  type="button"
                  className={SECONDARY_BUTTON}
                  disabled={chat.loadingOlder}
                  onClick={() => void chat.loadOlder()}
                >
                  {t('loadOlder')}
                </button>
              </div>
            )}
            {messages.length === 0 ? (
              <p className="rounded border border-dashed border-outline-variant px-4 py-6 text-body-md text-on-surface-variant">
                {t('empty')}
              </p>
            ) : (
              <ol role="log" aria-label={t('logLabel')} className="space-y-3">
                {messages.map((m) => (
                  <MessageItem
                    key={m.id}
                    message={m}
                    name={nameOf(m.author_id)}
                    isTeacher={m.author_id === ownerId}
                    canDelete={isOwner}
                    onDeleted={chat.markDeleted}
                    time={format.dateTime(new Date(m.created_at), {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  />
                ))}
              </ol>
            )}
          </div>

          {notice && (
            <p className="mt-4 rounded border border-outline-variant bg-surface-variant/40 px-4 py-3 text-body-sm text-on-surface-variant">
              {notice}
            </p>
          )}
          {canPost && (
            <Composer
              spaceId={spaceId}
              onPosted={chat.add}
              onRefused={(reason) => {
                if (reason === 'archived') setArchivedSeen(true)
                else if (reason === 'muted') patchStatus({ canPost: false, muted: true })
                else patchStatus({ canPost: false, locked: true })
              }}
            />
          )}
        </>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function MessageItem({
  message,
  name,
  isTeacher,
  canDelete,
  onDeleted,
  time,
}: {
  message: ChatMessage
  name: string
  isTeacher: boolean
  canDelete: boolean
  onDeleted: (id: string) => void
  time: string
}) {
  const t = useTranslations('classroom.chat')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function remove() {
    setBusy(true)
    setFailed(false)
    try {
      await deleteMessage(message.id)
      onDeleted(message.id)
      setConfirming(false)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li
      className={`rounded border border-outline-variant px-4 py-3 ${message.deleted ? 'bg-surface-variant/40 opacity-70' : 'bg-surface'}`}
    >
      <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-body-md font-semibold text-on-surface">{name}</span>
        {isTeacher && (
          <span className="rounded bg-primary-container px-2 py-0.5 text-label-caps uppercase text-on-primary-container">
            {t('teacherBadge')}
          </span>
        )}
        <time dateTime={message.created_at} className="text-body-sm text-on-surface-variant">
          {time}
        </time>
      </div>
      <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">
        {message.body}
      </p>
      {message.deleted && (
        <p className="mt-1 text-body-sm italic text-on-surface-variant">{t('deletedNote')}</p>
      )}
      {canDelete && !message.deleted && !confirming && (
        <button
          type="button"
          className="mt-2 text-body-sm font-semibold text-error hover:underline"
          onClick={() => setConfirming(true)}
        >
          {t('delete')}
        </button>
      )}
      {confirming && (
        <ConfirmInline
          question={t('deleteConfirm')}
          confirmLabel={t('delete')}
          busy={busy}
          onConfirm={() => void remove()}
          onCancel={() => setConfirming(false)}
        />
      )}
      {failed && (
        <div className="mt-2">
          <FormBanner>{t('deleteFailed')}</FormBanner>
        </div>
      )}
    </li>
  )
}

/* -------------------------------------------------------------------------- */

function Composer({
  spaceId,
  onPosted,
  onRefused,
}: {
  spaceId: string
  onPosted: (m: ChatMessage) => void
  onRefused: (reason: 'archived' | 'muted' | 'chat_locked') => void
}) {
  const t = useTranslations('classroom.chat')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send() {
    const body = draft.trim()
    if (!body || sending) return
    setSending(true)
    setError(null)
    try {
      onPosted(await postMessage(spaceId, body))
      setDraft('')
    } catch (e) {
      const reason = e instanceof ApiError ? e.details.reason : undefined
      if (reason === 'archived' || reason === 'muted' || reason === 'chat_locked') {
        onRefused(reason)
      } else if (e instanceof ApiError && e.code === 'RATE_LIMITED') {
        const seconds = typeof e.details.retry_after === 'number' ? e.details.retry_after : 60
        setError(t('tooFast', { seconds }))
      } else {
        setError(t('sendFailed'))
      }
    } finally {
      setSending(false)
    }
  }

  return (
    <form
      noValidate
      className="mt-4"
      onSubmit={(e) => {
        e.preventDefault()
        void send()
      }}
    >
      <label htmlFor="chat-composer" className="sr-only">
        {t('composerLabel')}
      </label>
      <textarea
        id="chat-composer"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter is a new line. Never while an input method
          // (Urdu, for one) is still composing a character.
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            void send()
          }
        }}
        rows={2}
        maxLength={1000}
        placeholder={t('placeholder')}
        className={FIELD}
      />
      <div className="mt-3 flex items-center justify-end">
        <button
          type="submit"
          disabled={sending || draft.trim() === ''}
          className={PRIMARY_BUTTON}
        >
          {sending ? t('sending') : t('send')}
        </button>
      </div>
      {error && (
        <div className="mt-3">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </form>
  )
}

/* -------------------------------------------------------------------------- */

function LockToggle({
  spaceId,
  locked,
  onChange,
}: {
  spaceId: string
  locked: boolean
  onChange: (space: SpaceDetail) => void
}) {
  const t = useTranslations('classroom.chat')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function toggle() {
    setBusy(true)
    setFailed(false)
    try {
      onChange(await updateSpace(spaceId, { chat_locked: !locked }))
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        type="button"
        className={`${SECONDARY_BUTTON} inline-flex items-center gap-2`}
        disabled={busy}
        onClick={() => void toggle()}
      >
        <LockIcon className="h-4 w-4" />
        {locked ? t('unlock') : t('lock')}
      </button>
      {failed && <FormBanner>{t('lockFailed')}</FormBanner>}
    </div>
  )
}
