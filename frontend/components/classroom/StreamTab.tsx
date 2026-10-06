'use client'

import { useCallback, useEffect, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { CalendarIcon } from '@/components/ui/Icon'
import {
  createAnnouncement,
  deleteAnnouncement,
  deleteAttachment,
  downloadAttachment,
  listAnnouncements,
  updateAnnouncement,
  uploadAnnouncementAttachment,
  viewAttachment,
} from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { Announcement, AnnouncementUpdateRequest } from '@/lib/api/types'
import { isoToLocalInput, localInputToIso, nowLocalInput } from '@/lib/datetime'
import { ConfirmInline } from './ConfirmInline'
import { FileSection } from './Files'
import { CARD, FIELD, LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * The stream — announcements, newest first (tdd.md §3.6, classroom Phase 3).
 *
 * A member never receives a scheduled post: the DATABASE withholds it
 * (`announcement_member_read`), so nothing here filters. The owner sees them
 * with a "Scheduled for" badge. Bodies are rendered as plain text — never HTML,
 * never auto-linked — so a post cannot carry markup to anyone's screen.
 */
export function StreamTab({
  spaceId,
  isOwner,
  canPost,
  authorName,
}: {
  spaceId: string
  isOwner: boolean
  /** Owner of a non-archived classroom. */
  canPost: boolean
  /** Every post is by the owner (the insert policy requires it). */
  authorName: string
}) {
  const t = useTranslations('classroom.stream')
  const [items, setItems] = useState<Announcement[] | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    listAnnouncements(spaceId, undefined, controller.signal)
      .then((page) => {
        setItems(page.items)
        setCursor(page.next_cursor)
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [spaceId])

  async function loadOlder() {
    if (!cursor) return
    setLoadingOlder(true)
    try {
      const page = await listAnnouncements(spaceId, cursor)
      // Keyset pages never overlap, but a post edited between requests must not
      // appear twice: merge by id.
      setItems((current) => {
        const seen = new Set((current ?? []).map((a) => a.id))
        return [...(current ?? []), ...page.items.filter((a) => !seen.has(a.id))]
      })
      setCursor(page.next_cursor)
    } catch {
      setFailed(true)
    } finally {
      setLoadingOlder(false)
    }
  }

  const replace = useCallback(
    (updated: Announcement) =>
      setItems((current) => (current ?? []).map((a) => (a.id === updated.id ? updated : a))),
    [],
  )
  const remove = useCallback(
    (id: string) => setItems((current) => (current ?? []).filter((a) => a.id !== id)),
    [],
  )

  return (
    <div className="space-y-4">
      {isOwner &&
        (canPost ? (
          <Composer spaceId={spaceId} onPosted={(a) => setItems((c) => [a, ...(c ?? [])])} />
        ) : (
          <p className="rounded border border-outline-variant bg-surface-variant/40 px-4 py-3 text-body-sm text-on-surface-variant">
            {t('archivedNoPosting')}
          </p>
        ))}

      {failed && items === null ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : items === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded border border-dashed border-outline-variant px-4 py-6 text-body-md text-on-surface-variant">
          {t('empty')}
        </p>
      ) : (
        <ul className="space-y-4">
          {items.map((a) => (
            <li key={a.id}>
              <Post
                announcement={a}
                authorName={authorName}
                canManage={isOwner && canPost}
                onChanged={replace}
                onDeleted={remove}
              />
            </li>
          ))}
        </ul>
      )}

      {failed && items !== null && <FormBanner>{t('loadFailed')}</FormBanner>}

      {cursor && (
        <div className="flex justify-center">
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={loadingOlder}
            onClick={() => void loadOlder()}
          >
            {loadingOlder ? t('loading') : t('loadOlder')}
          </button>
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function Composer({
  spaceId,
  onPosted,
}: {
  spaceId: string
  onPosted: (a: Announcement) => void
}) {
  const t = useTranslations('classroom.stream')
  const [body, setBody] = useState('')
  const [when, setWhen] = useState<'now' | 'later'>('now')
  const [at, setAt] = useState('')
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = body.trim() !== '' && (when === 'now' || at !== '') && !posting

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setPosting(true)
    setError(null)
    try {
      const created = await createAnnouncement(spaceId, {
        body: body.trim(),
        ...(when === 'later' ? { publish_at: localInputToIso(at) } : {}),
      })
      onPosted(created)
      setBody('')
      setWhen('now')
      setAt('')
    } catch (caught) {
      setError(
        caught instanceof ApiError &&
          caught.code === 'VALIDATION_ERROR' &&
          caught.fieldErrors().publish_at
          ? t('scheduleInvalid')
          : t('postFailed'),
      )
    } finally {
      setPosting(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className={CARD}>
      <label htmlFor="composer-body" className={LABEL}>
        {t('composerLabel')}
      </label>
      <textarea
        id="composer-body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        maxLength={5000}
        rows={4}
        placeholder={t('placeholder')}
        className={FIELD}
      />

      <fieldset className="mt-4">
        <legend className={LABEL}>{t('when')}</legend>
        <div className="flex flex-wrap gap-4">
          {(['now', 'later'] as const).map((option) => (
            <label
              key={option}
              className="flex items-center gap-2 text-body-md text-on-surface"
            >
              <input
                type="radio"
                name="composer-when"
                value={option}
                checked={when === option}
                onChange={() => setWhen(option)}
              />
              {option === 'now' ? t('postNow') : t('scheduleLater')}
            </label>
          ))}
        </div>
        {when === 'later' && (
          <div className="mt-3">
            <label htmlFor="composer-at" className={LABEL}>
              {t('scheduleLabel')}
            </label>
            <input
              id="composer-at"
              type="datetime-local"
              value={at}
              min={nowLocalInput()}
              onChange={(e) => setAt(e.target.value)}
              className={`force-ltr ${FIELD}`}
            />
          </div>
        )}
      </fieldset>

      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <button type="submit" disabled={!canSubmit} className={PRIMARY_BUTTON}>
          {posting ? t('posting') : when === 'later' ? t('scheduleButton') : t('post')}
        </button>
      </div>
    </form>
  )
}

/* -------------------------------------------------------------------------- */

function Post({
  announcement: a,
  authorName,
  canManage,
  onChanged,
  onDeleted,
}: {
  announcement: Announcement
  authorName: string
  canManage: boolean
  onChanged: (a: Announcement) => void
  onDeleted: (id: string) => void
}) {
  const t = useTranslations('classroom.stream')
  const tf = useTranslations('classroom.files')
  const format = useFormatter()
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(a.body)
  const [at, setAt] = useState(isoToLocalInput(a.publish_at))
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const when = format.dateTime(new Date(a.publish_at), {
    dateStyle: 'medium',
    timeStyle: 'short',
  })

  async function save() {
    const patch: AnnouncementUpdateRequest = {}
    if (body.trim() !== a.body) patch.body = body.trim()
    if (a.scheduled && at !== isoToLocalInput(a.publish_at))
      patch.publish_at = localInputToIso(at)
    if (Object.keys(patch).length === 0) {
      setEditing(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      onChanged(await updateAnnouncement(a.id, patch))
      setEditing(false)
    } catch (caught) {
      setError(
        caught instanceof ApiError &&
          caught.code === 'VALIDATION_ERROR' &&
          caught.fieldErrors().publish_at
          ? t('scheduleInvalid')
          : t('actionFailed'),
      )
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await deleteAnnouncement(a.id)
      onDeleted(a.id)
    } catch {
      setError(t('actionFailed'))
      setBusy(false)
    }
  }

  return (
    <article className={CARD}>
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-headline text-body-lg text-on-surface">{authorName}</p>
          <p className="text-body-sm text-on-surface-variant">
            {when}
            {a.updated_at !== a.created_at && ` · ${t('edited')}`}
          </p>
        </div>
        {a.scheduled && (
          <span className="flex items-center gap-1 rounded-full bg-secondary-container px-3 py-1 text-body-sm text-on-secondary-container">
            <CalendarIcon className="h-4 w-4" />
            {t('scheduledFor', { date: when })}
          </span>
        )}
      </header>

      {editing ? (
        <div className="space-y-3">
          <label htmlFor={`edit-${a.id}`} className="sr-only">
            {t('composerLabel')}
          </label>
          <textarea
            id={`edit-${a.id}`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={5000}
            rows={4}
            className={FIELD}
          />
          {a.scheduled && (
            <div>
              <label htmlFor={`edit-at-${a.id}`} className={LABEL}>
                {t('scheduleLabel')}
              </label>
              <input
                id={`edit-at-${a.id}`}
                type="datetime-local"
                value={at}
                min={nowLocalInput()}
                onChange={(e) => setAt(e.target.value)}
                className={`force-ltr ${FIELD}`}
              />
            </div>
          )}
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={busy || body.trim() === ''}
              onClick={() => void save()}
            >
              {busy ? t('saving') : t('save')}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={busy}
              onClick={() => {
                setEditing(false)
                setBody(a.body)
                setAt(isoToLocalInput(a.publish_at))
              }}
            >
              {t('cancel')}
            </button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">{a.body}</p>
      )}
      <FileSection
        heading={tf('attachments')}
        files={a.attachments}
        download={(f) => downloadAttachment(f.id)}
        view={(f) => viewAttachment(f.id)}
        upload={canManage ? (file) => uploadAnnouncementAttachment(a.id, file) : undefined}
        remove={canManage ? (f) => deleteAttachment(f.id) : undefined}
        onChange={(attachments) => onChanged({ ...a, attachments })}
      />

      {canManage && !editing && !confirmDelete && (
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" className={SECONDARY_BUTTON} onClick={() => setEditing(true)}>
            {t('edit')}
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON}
            onClick={() => setConfirmDelete(true)}
          >
            {t('delete')}
          </button>
        </div>
      )}
      {confirmDelete && (
        <ConfirmInline
          question={t('deleteConfirm')}
          confirmLabel={t('delete')}
          busy={busy}
          onConfirm={() => void remove()}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </article>
  )
}
