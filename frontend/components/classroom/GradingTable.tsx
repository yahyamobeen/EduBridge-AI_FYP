'use client'

import { useCallback, useEffect, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { UsersIcon } from '@/components/ui/Icon'
import {
  downloadSubmissionFile,
  getStudentWork,
  listSubmissions,
  saveGrade,
} from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { AssignmentDetail, StudentWork, SubmissionRow } from '@/lib/api/types'
import { StatusChip } from './AssignmentParts'
import { FileSection } from './Files'
import { SubmittedLink } from './SubmissionPanel'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * The teacher's view of an assignment: every active member, whether or not
 * they turned anything in (tdd.md §3.6). Owner only.
 *
 * A student's DRAFT is never shown — the database returns their work only
 * once it is turned in — so "not turned in yet" is all a teacher can know
 * about a draft. A saved grade stays private to the teacher until it is
 * returned; returning is one-way.
 */
export function GradingTable({
  assignment,
  canGrade,
}: {
  assignment: AssignmentDetail
  /** False for an archived classroom: the database refuses grade changes there. */
  canGrade: boolean
}) {
  const t = useTranslations('classroom.grading')
  const format = useFormatter()
  const [rows, setRows] = useState<SubmissionRow[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listSubmissions(assignment.id, controller.signal)
      .then((r) => setRows(r.rows))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [assignment.id])

  const replaceRow = useCallback(
    (work: StudentWork) =>
      setRows((current) =>
        (current ?? []).map((r) => (r.student_id === work.student_id ? { ...r, ...work } : r)),
      ),
    [],
  )

  const turnedIn = (rows ?? []).filter((r) => r.turned_in_at !== null).length

  return (
    <section aria-labelledby="grading-heading" className={CARD}>
      <h2 id="grading-heading" className={CARD_HEADING}>
        <UsersIcon className="h-5 w-5" />
        {t('heading')}
      </h2>
      {!canGrade && (
        <p className="mb-4 text-body-sm text-on-surface-variant">{t('archivedNoGrading')}</p>
      )}

      {failed ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : rows === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-body-md text-on-surface-variant">{t('empty')}</p>
      ) : (
        <>
          <p className="mb-3 text-body-sm text-on-surface-variant">
            {t('summary', { count: turnedIn, total: rows.length })}
          </p>
          <ul className="divide-y divide-outline-variant">
            {rows.map((r) => {
              const name = r.full_name ?? t('unnamed')
              const isOpen = open === r.student_id
              return (
                <li key={r.student_id} className="py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="space-y-1">
                      <p className="text-body-md text-on-surface">{name}</p>
                      <div className="flex flex-wrap items-center gap-2 text-body-sm text-on-surface-variant">
                        <StatusChip status={r.status} />
                        {r.grade !== null && assignment.points !== null && (
                          <span>
                            {format.number(r.grade)} / {assignment.points}
                          </span>
                        )}
                        {r.graded && (
                          <span>{r.returned_at ? t('returned') : t('notReturned')}</span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      className={SECONDARY_BUTTON}
                      aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? null : r.student_id)}
                    >
                      {isOpen ? t('close') : t('review')}
                    </button>
                  </div>
                  {isOpen && (
                    <StudentWorkPanel
                      assignment={assignment}
                      studentId={r.student_id}
                      name={name}
                      canGrade={canGrade}
                      onSaved={replaceRow}
                    />
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function StudentWorkPanel({
  assignment,
  studentId,
  name,
  canGrade,
  onSaved,
}: {
  assignment: AssignmentDetail
  studentId: string
  name: string
  canGrade: boolean
  onSaved: (work: StudentWork) => void
}) {
  const t = useTranslations('classroom.grading')
  const tf = useTranslations('classroom.files')
  const format = useFormatter()
  const [work, setWork] = useState<StudentWork | null>(null)
  const [failed, setFailed] = useState(false)
  const [grade, setGrade] = useState('')
  const [feedback, setFeedback] = useState('')
  const [saving, setSaving] = useState<'save' | 'return' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getStudentWork(assignment.id, studentId, controller.signal)
      .then((w) => {
        setWork(w)
        setGrade(w.grade !== null ? String(w.grade) : '')
        setFeedback(w.feedback)
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [assignment.id, studentId])

  const points = assignment.points
  const gradeValue = grade.trim() === '' ? null : Number(grade)
  const gradeValid =
    gradeValue === null ||
    (points !== null && Number.isFinite(gradeValue) && gradeValue >= 0 && gradeValue <= points)

  async function save(returnToStudent: boolean) {
    if (!gradeValid) {
      setError(t('gradeInvalid', { points: points ?? 0 }))
      return
    }
    setSaving(returnToStudent ? 'return' : 'save')
    setError(null)
    try {
      const next = await saveGrade(assignment.id, studentId, {
        grade: gradeValue,
        feedback: feedback.trim(),
        return_to_student: returnToStudent,
      })
      setWork(next)
      onSaved(next)
    } catch (caught) {
      setError(
        caught instanceof ApiError &&
          caught.code === 'VALIDATION_ERROR' &&
          caught.fieldErrors().grade
          ? t('gradeInvalid', { points: points ?? 0 })
          : t('failed'),
      )
    } finally {
      setSaving(null)
    }
  }

  const field = (n: string) => `grade-${assignment.id}-${studentId}-${n}`

  return (
    <div className="mt-3 rounded border border-outline-variant p-4">
      <h3 className="mb-2 text-label-caps uppercase text-on-surface-variant">
        {t('workHeading', { name })}
      </h3>
      {failed ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : work === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : (
        <>
          {work.turned_in_at === null ? (
            <p className="text-body-md text-on-surface-variant">{t('notTurnedIn')}</p>
          ) : (
            <>
              <p className="mb-2 text-body-sm text-on-surface-variant">
                {format.dateTime(new Date(work.turned_in_at), {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                })}
              </p>
              {work.body && (
                <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">
                  {work.body}
                </p>
              )}
              {work.link_url && (
                <div className="mt-2">
                  <p className="text-label-caps uppercase text-on-surface-variant">
                    {t('link')}
                  </p>
                  <SubmittedLink href={work.link_url} />
                </div>
              )}
              <FileSection
                heading={tf('studentFiles')}
                files={work.files}
                download={(f) => downloadSubmissionFile(f.id)}
              />
            </>
          )}

          {canGrade && (
            <form
              noValidate
              className="mt-4 space-y-3 border-t border-outline-variant pt-4"
              onSubmit={(e) => {
                e.preventDefault()
                if (saving === null) void save(false)
              }}
            >
              {points !== null ? (
                <div>
                  <label htmlFor={field('grade')} className={LABEL}>
                    {t('gradeLabel', { points })}
                  </label>
                  <input
                    id={field('grade')}
                    type="number"
                    inputMode="decimal"
                    min={0}
                    max={points}
                    step={0.01}
                    value={grade}
                    onChange={(e) => setGrade(e.target.value)}
                    aria-invalid={!gradeValid}
                    className={`force-ltr ${FIELD}`}
                  />
                </div>
              ) : (
                <p className="text-body-sm text-on-surface-variant">{t('noPoints')}</p>
              )}
              <div>
                <label htmlFor={field('feedback')} className={LABEL}>
                  {t('feedbackLabel')}
                </label>
                <textarea
                  id={field('feedback')}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  maxLength={5000}
                  rows={3}
                  className={FIELD}
                />
              </div>
              {error && <FormBanner>{error}</FormBanner>}
              <div className="flex flex-wrap justify-end gap-3">
                <button type="submit" className={SECONDARY_BUTTON} disabled={saving !== null}>
                  {saving === 'save' ? t('saving') : t('save')}
                </button>
                <button
                  type="button"
                  className={PRIMARY_BUTTON}
                  disabled={saving !== null}
                  onClick={() => void save(true)}
                >
                  {saving === 'return' ? t('saving') : t('saveAndReturn')}
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  )
}
