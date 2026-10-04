'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { createAssignment, listChapters, updateAssignment } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type {
  AssignmentCreateRequest,
  AssignmentDetail,
  AssignmentUpdateRequest,
  ChapterRef,
} from '@/lib/api/types'
import { isoToLocalInput, localInputToIso, nowLocalInput } from '@/lib/datetime'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * Create an assignment, or edit one (`initial`). Owner only — the caller
 * renders it only for the owner of an active classroom.
 *
 * An edit sends ONLY what changed, and an emptied optional field is sent as
 * `null` (the API clears `due_at`, `points` and `chapter_id` that way). A
 * schedule can be set when creating, and moved only while the assignment is
 * still scheduled — the same rule as announcements.
 */
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
  onSaved: (a: AssignmentDetail) => void
  onCancel: () => void
}) {
  const t = useTranslations('classroom.assignment')
  const tw = useTranslations('classroom.classwork')
  const [title, setTitle] = useState(initial?.title ?? '')
  const [instructions, setInstructions] = useState(initial?.instructions ?? '')
  const [points, setPoints] = useState(initial?.points != null ? String(initial.points) : '')
  const [due, setDue] = useState(initial?.due_at ? isoToLocalInput(initial.due_at) : '')
  const [chapterId, setChapterId] = useState(initial?.chapter?.id ?? '')
  const [chapters, setChapters] = useState<ChapterRef[] | null>(null)
  const [when, setWhen] = useState<'now' | 'later'>(initial?.scheduled ? 'later' : 'now')
  const [at, setAt] = useState(initial?.scheduled ? isoToLocalInput(initial.publish_at) : '')
  const [saving, setSaving] = useState(false)
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
      onSaved(
        initial && patch
          ? await updateAssignment(initial.id, patch)
          : await createAssignment(spaceId, createBody()),
      )
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
          {saving
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
