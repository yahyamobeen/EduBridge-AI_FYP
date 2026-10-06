'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { ErrorText, FormBanner } from '@/components/ui/FormFeedback'
import { useRouter } from '@/i18n/navigation'
import { createSpace, getEnums, listSubjects } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { BoardCode, EnumsResponse, SubjectOption } from '@/lib/api/types'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON } from './styles'

/**
 * Create a classroom — POST /spaces.
 *
 * Board → class → subject, because a subject row exists once per (board,
 * class): choosing the subject fixes all three, and it is what the teacher
 * declares they teach (prd.md §15 CL-2). Boards and class levels come from
 * /reference/enums and subjects from /reference/subjects — never a literal
 * list, which is the mistake Settings.tsx records the prototype making.
 */
export function CreateClassForm() {
  const t = useTranslations('classroom.create')
  const router = useRouter()

  const [enums, setEnums] = useState<EnumsResponse | null>(null)
  const [board, setBoard] = useState<BoardCode | ''>('')
  const [classLevel, setClassLevel] = useState<number | ''>('')
  const [subjects, setSubjects] = useState<SubjectOption[] | null>(null)
  const [subjectsFailed, setSubjectsFailed] = useState(false)
  const [subjectId, setSubjectId] = useState('')
  const [title, setTitle] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    const controller = new AbortController()
    getEnums(controller.signal)
      .then(setEnums)
      .catch(() => {})
    return () => controller.abort()
  }, [])

  // The subject list belongs to one (board, class) pair, so changing either
  // discards it and anything chosen from it. Done in the handlers, not in the
  // effect below, so the effect only ever sets state from an awaited response.
  function resetSubjects() {
    setSubjectId('')
    setSubjects(null)
    setSubjectsFailed(false)
  }

  useEffect(() => {
    if (board === '' || classLevel === '') return
    const controller = new AbortController()
    listSubjects(board, classLevel, controller.signal)
      .then((r) => setSubjects(r.subjects))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setSubjectsFailed(true)
      })
    return () => controller.abort()
  }, [board, classLevel])

  const canSubmit = title.trim() !== '' && subjectId !== '' && !submitting

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    setFieldErrors({})
    try {
      const space = await createSpace({ title: title.trim(), subject_id: subjectId })
      router.push(`/teacher/classroom/${space.id}`)
    } catch (caught) {
      setSubmitting(false)
      if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
        if (caught.details.reason === 'classroom_limit') setError(t('limit'))
        else setFieldErrors(caught.fieldErrors())
      } else if (caught instanceof ApiError && caught.code === 'FORBIDDEN_SCOPE') {
        setError(t('forbidden'))
      } else {
        setError(t('failed'))
      }
    }
  }

  return (
    <form onSubmit={submit} noValidate className={CARD}>
      <h2 className={CARD_HEADING}>{t('heading')}</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="create-board" className={LABEL}>
            {t('boardLabel')}
          </label>
          <select
            id="create-board"
            value={board}
            onChange={(e) => {
              resetSubjects()
              setBoard(e.target.value as BoardCode | '')
            }}
            disabled={enums === null}
            className={FIELD}
          >
            <option value="">{t('choose')}</option>
            {enums?.boards.map((b) => (
              <option key={b.code} value={b.code}>
                {b.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="create-class" className={LABEL}>
            {t('classLabel')}
          </label>
          <select
            id="create-class"
            value={classLevel}
            onChange={(e) => {
              resetSubjects()
              setClassLevel(e.target.value === '' ? '' : Number(e.target.value))
            }}
            disabled={enums === null}
            className={FIELD}
          >
            <option value="">{t('choose')}</option>
            {enums?.class_levels.map((level) => (
              <option key={level} value={level}>
                {t('classOption', { level })}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-4">
        <label htmlFor="create-subject" className={LABEL}>
          {t('subjectLabel')}
        </label>
        <select
          id="create-subject"
          value={subjectId}
          onChange={(e) => setSubjectId(e.target.value)}
          disabled={subjects === null || subjects.length === 0}
          aria-describedby={fieldErrors.subject_id ? 'create-subject-error' : undefined}
          className={FIELD}
        >
          <option value="">
            {board === '' || classLevel === ''
              ? t('subjectNeedsClass')
              : subjects === null && !subjectsFailed
                ? t('subjectsLoading')
                : t('choose')}
          </option>
          {subjects?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {subjectsFailed && (
          <p role="status" className="mt-1.5 text-body-sm text-on-surface-variant">
            {t('subjectsFailed')}
          </p>
        )}
        {fieldErrors.subject_id && (
          <ErrorText id="create-subject-error">{t('subjectInvalid')}</ErrorText>
        )}
      </div>

      <div className="mt-4">
        <label htmlFor="create-title" className={LABEL}>
          {t('titleLabel')}
        </label>
        <input
          id="create-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          placeholder={t('titlePlaceholder')}
          aria-describedby={fieldErrors.title ? 'create-title-error' : undefined}
          className={FIELD}
        />
        {fieldErrors.title && (
          <ErrorText id="create-title-error">{t('titleInvalid')}</ErrorText>
        )}
      </div>

      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button type="submit" disabled={!canSubmit} className={PRIMARY_BUTTON}>
          {submitting ? t('creating') : t('submit')}
        </button>
      </div>
    </form>
  )
}
