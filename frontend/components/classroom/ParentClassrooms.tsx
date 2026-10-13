'use client'

import { useEffect, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { RequireRole } from '@/components/app/SessionGuard'
import { FormBanner } from '@/components/ui/FormFeedback'
import { getParentClassrooms } from '@/lib/api/endpoints'
import type { ParentAssignment, ParentChild, ParentOverviewResponse } from '@/lib/api/types'
import { StatusChip } from './AssignmentParts'
import { CARD, CARD_HEADING } from './styles'

/**
 * The parent's classroom overview — `/parent/classroom` (prd.md CL-10, classroom
 * Phase 8).
 *
 * ⚠️ READ-ONLY, AND NOTHING TO CLICK. No link into a classroom, no tab, no
 *    button: a classroom's own pages carry the stream, the chat and classmates'
 *    names, none of which a parent may see (prd.md §4.2). Everything here comes
 *    from one call, `GET /api/parent/classrooms`, which the DATABASE limits to
 *    a verified child's deadlines, derived status and RETURNED grades — the
 *    feedback, the work and the chat never reach this page, so nothing here
 *    has to hide them.
 */
export function ParentClassrooms() {
  return <RequireRole allow={['parent']}>{() => <ParentOverview />}</RequireRole>
}

export function ParentOverview() {
  const t = useTranslations('classroom.parent')
  const [data, setData] = useState<ParentOverviewResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getParentClassrooms(controller.signal)
      .then(setData)
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [])

  return (
    <>
      <header className="mb-6">
        <h1 className="font-headline text-headline-lg text-on-background">{t('title')}</h1>
        <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
      </header>
      <p className="mb-6 rounded-md border border-secondary/30 bg-secondary-container/40 px-4 py-3 text-body-sm text-on-surface">
        {t('privacy')}
      </p>

      {failed ? (
        <FormBanner>{t('unavailable')}</FormBanner>
      ) : data === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : data.children.length === 0 ? (
        <p className="rounded border border-dashed border-outline-variant px-4 py-6 text-body-md text-on-surface-variant">
          {t('noChildren')}
        </p>
      ) : (
        <div className="space-y-10">
          {data.children.map((child) => (
            <ChildSection key={child.student_id} child={child} />
          ))}
        </div>
      )}
    </>
  )
}

function ChildSection({ child }: { child: ParentChild }) {
  const t = useTranslations('classroom.parent')
  const name = child.full_name ?? t('unnamedChild')
  return (
    <section aria-label={name}>
      <h2 className="mb-4 font-headline text-headline-md text-on-background">{name}</h2>
      {child.classrooms.length === 0 ? (
        <p className="text-body-md text-on-surface-variant">{t('noClassrooms', { name })}</p>
      ) : (
        <div className="grid grid-cols-1 gap-gutter lg:grid-cols-2">
          {child.classrooms.map((room) => (
            <section
              key={room.space_id}
              className={CARD}
              aria-labelledby={`room-${room.space_id}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 id={`room-${room.space_id}`} className={CARD_HEADING}>
                  {room.title}
                </h3>
                {room.status === 'archived' && (
                  <span className="rounded-full bg-surface-variant px-3 py-1 text-body-sm text-on-surface-variant">
                    {t('archived')}
                  </span>
                )}
              </div>
              <p className="mb-4 text-body-sm text-on-surface-variant">
                {t('classroomLine', {
                  subject: room.subject_name,
                  teacher: room.teacher_name ?? t('unknownTeacher'),
                })}
              </p>
              {room.assignments.length === 0 ? (
                <p className="text-body-md text-on-surface-variant">{t('noAssignments')}</p>
              ) : (
                <ul className="divide-y divide-outline-variant">
                  {room.assignments.map((a) => (
                    <AssignmentRow key={a.id} assignment={a} />
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </section>
  )
}

function AssignmentRow({ assignment: a }: { assignment: ParentAssignment }) {
  const t = useTranslations('classroom.parent')
  const format = useFormatter()
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div>
        <p className="text-body-md text-on-surface">{a.title}</p>
        <p className="text-body-sm text-on-surface-variant">
          {a.due_at
            ? t('due', {
                date: format.dateTime(new Date(a.due_at), {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                }),
              })
            : t('noDue')}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {a.grade !== null && (
          <span className="text-body-md font-semibold text-on-surface">
            {a.points !== null
              ? t('grade', { grade: a.grade, points: a.points })
              : t('gradeOnly', { grade: a.grade })}
          </span>
        )}
        <StatusChip status={a.status} />
      </div>
    </li>
  )
}
