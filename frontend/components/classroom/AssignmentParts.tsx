'use client'

import { useFormatter, useTranslations } from 'next-intl'
import { CalendarIcon } from '@/components/ui/Icon'
import type { AssignmentSummary, WorkStatus } from '@/lib/api/types'

/**
 * Small pieces shared by the classwork list, the assignment view and the
 * grading table. The status itself is derived by the SERVER (status.py) from
 * the timestamps; this only names and colours it.
 */

const CHIP: Record<WorkStatus, string> = {
  assigned: 'bg-surface-container-high text-on-surface-variant',
  turned_in: 'bg-secondary-container text-on-secondary-container',
  turned_in_late: 'border border-status-pending text-status-pending',
  missing: 'bg-error-container text-on-error-container',
  graded: 'border border-status-verified text-status-verified',
}

export function StatusChip({ status }: { status: WorkStatus }) {
  const t = useTranslations('classroom.status')
  return (
    <span className={`inline-block rounded-full px-3 py-1 text-body-sm ${CHIP[status]}`}>
      {t(status)}
    </span>
  )
}

/** Due date, points, chapter and — for the owner — the scheduled badge. */
export function AssignmentMeta({ assignment: a }: { assignment: AssignmentSummary }) {
  const t = useTranslations('classroom.classwork')
  const format = useFormatter()
  const at = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: 'medium', timeStyle: 'short' })

  return (
    // A span, not a <p>: this also renders inside the list's <button>, which takes phrasing content only.
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-body-sm text-on-surface-variant">
      <span>{a.due_at ? t('due', { date: at(a.due_at) }) : t('noDue')}</span>
      {a.points !== null && <span>{t('points', { points: a.points })}</span>}
      {a.chapter && (
        <span>{t('chapter', { number: a.chapter.number, title: a.chapter.title })}</span>
      )}
      {a.scheduled && (
        <span className="flex items-center gap-1 rounded-full bg-secondary-container px-3 py-1 text-on-secondary-container">
          <CalendarIcon className="h-4 w-4" />
          {t('scheduledFor', { date: at(a.publish_at) })}
        </span>
      )}
    </span>
  )
}
