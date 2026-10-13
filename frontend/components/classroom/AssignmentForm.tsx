'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import {
  createAssignment,
  listChapters,
  updateAssignment,
  uploadAssignmentAttachment,
} from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type {
  AssignmentCreateRequest,
  AssignmentDetail,
  AssignmentUpdateRequest,
  ChapterRef,
  FileMeta,
} from '@/lib/api/types'
import { isoToLocalInput, localInputToIso, nowLocalInput } from '@/lib/datetime'
import { ACCEPT, earlyRefusal } from '@/lib/files'
import { useSizeLabel } from './Files'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * Create an assignment, or edit one (`initial`). Owner only — the caller
 * renders it only for the owner of an active classroom.
 *
 * An edit sends ONLY what changed, and an emptied optional field is sent as
 * `null` (the API clears `due_at`, `points` and `chapter_id` that way). A
 * schedule can be set when creating, and moved only while the assignment is
 * still scheduled — the same rule as announcements.
 *
 * Creating can carry files (Phase 6b): they are held here, checked, and
 * uploaded one by one once the assignment exists — an upload needs its id, and
 * one request with several files is the multipart body the server refuses. A
 * file that fails does not undo the assignment: `onSaved` names it, and the
 * assignment view offers "Add a file" again. Editing manages files in
 * `AssignmentView`, as before.
 */

/** Ten per assignment, the database's limit (app.add_material_attachment). */
const MAX_FILES = 10
export function AssignmentForm({
  spaceId,
  subjectId,
  initial,
  onSaved,
  onCancel,
}: {
  spaceId: string
  subjectId: string
  initial?: AssignmentDetail
  /** `notAttached`: names of files picked while creating that could not be added. */
  onSaved: (a: AssignmentDetail, notAttached?: string[]) => void
  onCancel: () => void
}) {
  const t = useTranslations('classroom.assignment')
  const tw = useTranslations('classroom.classwork')
  const tf = useTranslations('classroom.files')
  const sizeLabel = useSizeLabel()
  const fileInput = useRef<HTMLInputElement>(null)
  const fileInputId = useId()
  const [title, setTitle] = useState(initial?.title ?? '')
  const [instructions, setInstructions] = useState(initial?.instructions ?? '')
  const [points, setPoints] = useState(initial?.points != null ? String(initial.points) : '')
  const [due, setDue] = useState(initial?.due_at ? isoToLocalInput(initial.due_at) : '')
  const [chapterId, setChapterId] = useState(initial?.chapter?.id ?? '')
  const [chapters, setChapters] = useState<ChapterRef[] | null>(null)
  const [when, setWhen] = useState<'now' | 'later'>(initial?.scheduled ? 'later' : 'now')
  const [at, setAt] = useState(initial?.scheduled ? isoToLocalInput(initial.publish_at) : '')
  const [pending, setPending] = useState<File[]>([])
  const [pendingError, setPendingError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listChapters(subjectId, controller.signal)
      .then((r) => setChapters(r.chapters))
      .catch((e) => {
        // No picker is better than a broken form: the tag is optional.
        if (!(e instanceof DOMException && e.name === 'AbortError')) setChapters([])
      })
    return () => controller.abort()
  }, [subjectId])

  const pointsValue = points.trim() === '' ? null : Number(points)
  const pointsValid =
    pointsValue === null ||
    (Number.isInteger(pointsValue) && pointsValue >= 1 && pointsValue <= 1000)
  const canSchedule = !initial || initial.scheduled
  const canSubmit =
    title.trim() !== '' && pointsValid && (when === 'now' || at !== '') && !saving

  function createBody(): AssignmentCreateRequest {
    return {
      title: title.trim(),
      ...(instructions.trim() ? { instructions: instructions.trim() } : {}),
      ...(pointsValue !== null ? { points: pointsValue } : {}),
      ...(due ? { due_at: localInputToIso(due) } : {}),
      ...(chapterId ? { chapter_id: chapterId } : {}),
      ...(when === 'later' ? { publish_at: localInputToIso(at) } : {}),
    }
  }

  function changes(a: AssignmentDetail): AssignmentUpdateRequest {
    const patch: AssignmentUpdateRequest = {}
    if (title.trim() !== a.title) patch.title = title.trim()
    if (instructions.trim() !== a.instructions) patch.instructions = instructions.trim()
    if (pointsValue !== a.points) patch.points = pointsValue
    if (due !== (a.due_at ? isoToLocalInput(a.due_at) : '')) {
      patch.due_at = due === '' ? null : localInputToIso(due)
    }
    if ((chapterId || null) !== (a.chapter?.id ?? null)) patch.chapter_id = chapterId || null
    if (a.scheduled && at !== isoToLocalInput(a.publish_at))
      patch.publish_at = localInputToIso(at)
    return patch
  }

  function explain(caught: unknown): string {
    if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
      const fields = caught.fieldErrors()
      if (fields.due_at) return t('dueInvalid')
      if (fields.publish_at) return t('scheduleInvalid')
      // Bounds are checked here before sending, so a points refusal from the
      // server means grades already exceed the new value.
      if (fields.points) return t('pointsBelowGrades')
      if (fields.chapter_id) return t('chapterInvalid')
    }
    return t('failed')
  }

  function pick(chosen: FileList | null) {
    setPendingError(null)
    const next = [...pending]
    for (const file of Array.from(chosen ?? [])) {
      const early = earlyRefusal(file)
      if (early) {
        setPendingError(tf(early))
      } else if (next.length >= MAX_FILES) {
        setPendingError(tf('tooManyFiles'))
        break
      } else {
        next.push(file)
      }
    }
    setPending(next)
    if (fileInput.current) fileInput.current.value = ''
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    let patch: AssignmentUpdateRequest | null = null
    if (initial) {
      patch = changes(initial)
      if (Object.keys(patch).length === 0) {
        onSaved(initial)
        return
      }
    }
    setSaving(true)
    setError(null)
    try {
      if (initial && patch) {
        onSaved(await updateAssignment(initial.id, patch))
        return
      }
      const created = await createAssignment(spaceId, createBody())
      setUploading(true)
      const attached: FileMeta[] = []
      const notAttached: string[] = []
      for (const file of pending) {
        try {
          attached.push(await uploadAssignmentAttachment(created.id, file))
        } catch {
          notAttached.push(file.name)
        }
      }
      onSaved({ ...created, attachments: [...created.attachments, ...attached] }, notAttached)
    } catch (caught) {
      setError(explain(caught))
      setSaving(false)
    }
  }

  const id = (name: string) => `assignment-${initial?.id ?? 'new'}-${name}`

  return (
    <form onSubmit={submit} noValidate className={CARD}>
      <h2 className={CARD_HEADING}>{initial ? t('editHeading') : t('formHeading')}</h2>

      <div className="space-y-4">
        <div>
          <label htmlFor={id('title')} className={LABEL}>
            {t('titleLabel')}
          </label>
          <input
            id={id('title')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            className={FIELD}
          />
        </div>

        <div>
          <label htmlFor={id('instructions')} className={LABEL}>
            {t('instructionsLabel')}
          </label>
          <textarea
            id={id('instructions')}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            maxLength={10000}
            rows={4}
            className={FIELD}
          />
        </div>

        {!initial && (
          <div>
            <p className={LABEL}>{tf('attachments')}</p>
            {pending.length > 0 && (
              <ul className="mb-2 divide-y divide-outline-variant rounded border border-outline-variant">
                {pending.map((file, index) => (
                  <li
                    key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
                    className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                  >
                    <span className="min-w-0 break-all text-body-md text-on-surface">
                      {file.name}
                    </span>
                    <span className="flex items-center gap-3 text-body-sm text-on-surface-variant">
                      {sizeLabel(file.size)}
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => setPending(pending.filter((_, i) => i !== index))}
                        aria-label={tf('removeLabel', { name: file.name })}
                        className="text-error underline disabled:opacity-50"
                      >
                        {tf('remove')}
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <input
              ref={fileInput}
              id={fileInputId}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              disabled={saving}
              onChange={(e) => pick(e.target.files)}
            />
            <label
              htmlFor={fileInputId}
              className={`${SECONDARY_BUTTON} inline-block cursor-pointer ${saving ? 'opacity-50' : ''}`}
            >
              {tf('add')}
            </label>
            <p className="mt-1 text-body-sm text-on-surface-variant">{tf('hint')}</p>
            {pendingError && (
              <div className="mt-2">
                <FormBanner>{pendingError}</FormBanner>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={id('points')} className={LABEL}>
              {t('pointsLabel')}
            </label>
            <input
              id={id('points')}
              type="number"
              inputMode="numeric"
              min={1}
              max={1000}
              step={1}
              value={points}
              onChange={(e) => setPoints(e.target.value)}
              aria-invalid={!pointsValid}
              aria-describedby={pointsValid ? undefined : id('points-error')}
              className={`force-ltr ${FIELD}`}
            />
            {!pointsValid && (
              <p id={id('points-error')} className="mt-1 text-body-sm text-error">
                {t('pointsInvalid')}
              </p>
            )}
          </div>
          <div>
            <label htmlFor={id('due')} className={LABEL}>
              {t('dueLabel')}
            </label>
            <input
              id={id('due')}
              type="datetime-local"
              value={due}
              min={nowLocalInput()}
              onChange={(e) => setDue(e.target.value)}
              className={`force-ltr ${FIELD}`}
            />
          </div>
        </div>

        {chapters !== null && chapters.length === 0 && !chapterId ? (
          <div>
            <p className={LABEL}>{t('chapterLabel')}</p>
            <p className="text-body-sm text-on-surface-variant">{t('chaptersUnavailable')}</p>
          </div>
        ) : (
          <div>
            <label htmlFor={id('chapter')} className={LABEL}>
              {t('chapterLabel')}
            </label>
            <select
              id={id('chapter')}
              value={chapterId}
              disabled={chapters === null}
              onChange={(e) => setChapterId(e.target.value)}
              className={FIELD}
            >
              <option value="">{t('noChapter')}</option>
              {initial?.chapter && !chapters?.some((c) => c.id === initial.chapter?.id) && (
                <option value={initial.chapter.id}>
                  {tw('chapter', {
                    number: initial.chapter.number,
                    title: initial.chapter.title,
                  })}
                </option>
              )}
              {(chapters ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {tw('chapter', { number: c.number, title: c.title })}
                </option>
              ))}
            </select>
          </div>
        )}

        {canSchedule && (
          <fieldset>
            {!initial && (
              <>
                <legend className={LABEL}>{t('when')}</legend>
                <div className="flex flex-wrap gap-4">
                  {(['now', 'later'] as const).map((option) => (
                    <label
                      key={option}
                      className="flex items-center gap-2 text-body-md text-on-surface"
                    >
                      <input
                        type="radio"
                        name={id('when')}
                        value={option}
                        checked={when === option}
                        onChange={() => setWhen(option)}
                      />
                      {option === 'now' ? t('postNow') : t('scheduleLater')}
                    </label>
                  ))}
                </div>
              </>
            )}
            {when === 'later' && (
              <div className="mt-3">
                <label htmlFor={id('at')} className={LABEL}>
                  {t('scheduleLabel')}
                </label>
                <input
                  id={id('at')}
                  type="datetime-local"
                  value={at}
                  min={nowLocalInput()}
                  onChange={(e) => setAt(e.target.value)}
                  className={`force-ltr ${FIELD}`}
                />
              </div>
            )}
          </fieldset>
        )}
      </div>

      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}

      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <button type="button" className={SECONDARY_BUTTON} disabled={saving} onClick={onCancel}>
          {t('cancel')}
        </button>
        <button type="submit" disabled={!canSubmit} className={PRIMARY_BUTTON}>
          {uploading
            ? tf('addingFiles')
            : saving
              ? t('saving')
              : initial
                ? t('save')
                : when === 'later'
                  ? t('schedule')
                  : t('create')}
        </button>
      </div>
    </form>
  )
}
