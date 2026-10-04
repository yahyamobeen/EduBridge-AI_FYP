'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowLeftIcon } from '@/components/ui/Icon'
import { deleteAssignment, getAssignment } from '@/lib/api/endpoints'
import type { AssignmentDetail, MySubmission } from '@/lib/api/types'
import { AssignmentForm } from './AssignmentForm'
import { AssignmentMeta, StatusChip } from './AssignmentParts'
import { ConfirmInline } from './ConfirmInline'
import { GradingTable } from './GradingTable'
import { SubmissionPanel } from './SubmissionPanel'
import { CARD, DANGER_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * One assignment, opened from the Classwork tab. A member gets their own
 * submission panel; the owner gets edit, delete and the grading table. Which
 * of the two is decided by the server's answer (`my_submission` is present
 * only in a member's view), not by the session role.
 */
export function AssignmentView({
  assignmentId,
  subjectId,
  isOwner,
  canManage,
  onBack,
  onChanged,
  onDeleted,
}: {
  assignmentId: string
  subjectId: string
  isOwner: boolean
  /** Owner of an active classroom. */
  canManage: boolean
  onBack: () => void
  onChanged: (a: AssignmentDetail) => void
  onDeleted: (id: string) => void
}) {
  const t = useTranslations('classroom.assignment')
  const [assignment, setAssignment] = useState<AssignmentDetail | null>(null)
  const [failed, setFailed] = useState(false)
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getAssignment(assignmentId, controller.signal)
      .then(setAssignment)
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [assignmentId])

  function changed(next: AssignmentDetail) {
    setAssignment(next)
    onChanged(next)
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await deleteAssignment(assignmentId)
      onDeleted(assignmentId) // unmounts this view
    } catch {
      setError(t('deleteFailed'))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
        {t('back')}
      </button>

      {failed ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : assignment === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : editing ? (
        <AssignmentForm
          spaceId={assignment.space_id}
          subjectId={subjectId}
          initial={assignment}
          onSaved={(next) => {
            changed(next)
            setEditing(false)
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <article className={CARD}>
            <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
              <h2 className="font-headline text-headline-md text-on-surface">
                {assignment.title}
              </h2>
              {assignment.my_status && <StatusChip status={assignment.my_status} />}
            </header>
            <AssignmentMeta assignment={assignment} />
            <p className="mt-4 whitespace-pre-wrap break-words text-body-md text-on-surface">
              {assignment.instructions || t('noInstructions')}
            </p>

            {isOwner && canManage && !confirmDelete && (
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  className={SECONDARY_BUTTON}
                  onClick={() => setEditing(true)}
                >
                  {t('edit')}
                </button>
                <button
                  type="button"
                  className={DANGER_BUTTON}
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

          {assignment.my_submission && (
            <SubmissionPanel
              assignment={{ ...assignment, my_submission: assignment.my_submission }}
              onChange={(sub: MySubmission) =>
                changed({
                  ...assignment,
                  my_submission: sub,
                  my_status: sub.status,
                  my_grade: sub.grade,
                })
              }
            />
          )}
          {isOwner && <GradingTable assignment={assignment} canGrade={canManage} />}
        </>
      )}
    </div>
  )
}
