'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { ArrowIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { listSpaces } from '@/lib/api/endpoints'
import type { SpaceSummary } from '@/lib/api/types'

/**
 * The dashboard's classroom card, for a student ("My classes") or a teacher
 * ("My classrooms") — classroom Phase 6c. It replaced a `PlaceholderCard` that
 * kept saying "Not available yet" for a feature that had worked since Phase 2
 * (owner report, 2026-10-05).
 *
 * It shows up to three ACTIVE classrooms from `GET /api/spaces`, each linking
 * to its page, and "All classrooms" for the rest (archived ones included). It
 * never shows the "Not available yet" pill — not even when the request fails:
 * then it is just the way in, because the feature is there.
 */

const SHOWN = 3

export function ClassroomsCard({ role, span }: { role: 'student' | 'teacher'; span: 4 | 8 }) {
  const t = useTranslations('dashboard.cards')
  const [spaces, setSpaces] = useState<SpaceSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const basePath = role === 'teacher' ? '/teacher/classroom' : '/classroom'

  useEffect(() => {
    const controller = new AbortController()
    listSpaces(controller.signal)
      .then((r) => setSpaces(r.spaces))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [])

  const active = (spaces ?? []).filter((s) => s.status === 'active').slice(0, SHOWN)
  const empty = spaces !== null && spaces.length === 0

  return (
    <section
      className={`col-span-1 rounded-md border border-outline-variant bg-surface p-6 ${
        span === 8 ? 'md:col-span-8' : 'md:col-span-4'
      }`}
    >
      <h3 className="mb-2 font-headline text-headline-md text-on-surface">
        {role === 'teacher' ? t('spacesTitle') : t('myClassesTitle')}
      </h3>
      <p className="mb-4 text-body-sm text-on-surface-variant">
        {role === 'teacher' ? t('spacesBody') : t('myClassesBody')}
      </p>

      {spaces === null && !failed && (
        <p role="status" className="text-body-sm text-on-surface-variant">
          {t('classesLoading')}
        </p>
      )}

      {empty ? (
        <>
          <p className="mb-3 text-body-md text-on-surface">
            {role === 'teacher' ? t('classesEmptyTeacher') : t('classesEmptyStudent')}
          </p>
          <CardLink href={basePath}>
            {role === 'teacher' ? t('createClassroom') : t('joinClass')}
          </CardLink>
        </>
      ) : (
        <>
          {active.length > 0 && (
            <ul className="mb-4 divide-y divide-outline-variant rounded border border-outline-variant">
              {active.map((s) => (
                <li key={s.id}>
                  <Link
                    href={`${basePath}/${s.id}`}
                    className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2 hover:bg-surface-container"
                  >
                    <span className="min-w-0 break-words text-body-md font-semibold text-primary">
                      {s.title}
                    </span>
                    <span className="text-body-sm text-on-surface-variant">
                      {role === 'teacher' && s.member_count !== null
                        ? t('memberCount', { count: s.member_count })
                        : s.subject.name}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {(spaces !== null || failed) && (
            <CardLink href={basePath}>{t('allClassrooms')}</CardLink>
          )}
        </>
      )}
    </section>
  )
}

function CardLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:text-primary-container"
    >
      {children}
      <ArrowIcon className="h-4 w-4 rtl:-scale-x-100" />
    </Link>
  )
}
