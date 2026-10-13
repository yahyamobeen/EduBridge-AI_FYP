'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { RequireRole } from '@/components/app/SessionGuard'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowIcon, BookIcon, CalendarIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { listSpaces } from '@/lib/api/endpoints'
import type { MeResponse, SpaceSummary } from '@/lib/api/types'
import { CreateClassForm } from './CreateClassForm'
import { JoinClassForm } from './JoinClassForm'

/**
 * The two classroom lists — `/classroom` for students, `/teacher/classroom`
 * for teachers. Separate routes with exact `RequireRole` role lists, sharing
 * this module, so the role boundary is a route boundary (navigation.ts is an
 * RBAC map, and each entry points at a page that admits only its role).
 */
export function StudentClassrooms() {
  return (
    <RequireRole allow={['student']}>
      {(me) => <ClassroomsBody me={me} basePath="/classroom" form={<JoinClassForm />} />}
    </RequireRole>
  )
}

export function TeacherClassrooms() {
  return (
    <RequireRole allow={['teacher']}>
      {(me) => (
        <ClassroomsBody me={me} basePath="/teacher/classroom" form={<CreateClassForm />} />
      )}
    </RequireRole>
  )
}

function ClassroomsBody({
  me,
  basePath,
  form,
}: {
  me: MeResponse
  basePath: string
  form: React.ReactNode
}) {
  const t = useTranslations('classroom')
  const role = me.role === 'teacher' ? 'teacher' : 'student'
  const [spaces, setSpaces] = useState<SpaceSummary[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    listSpaces(controller.signal)
      .then((r) => setSpaces(r.spaces))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [])

  return (
    <>
      <header className="mb-8">
        <h1 className="font-headline text-headline-lg text-on-background">
          {t(`${role}.title`)}
        </h1>
        <p className="text-body-md text-on-surface-variant">{t(`${role}.intro`)}</p>
      </header>

      <div className="grid grid-cols-1 gap-gutter lg:grid-cols-3">
        <section aria-labelledby="classroom-list-heading" className="space-y-4 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              id="classroom-list-heading"
              className="font-headline text-headline-md text-on-surface"
            >
              {t('list.heading')}
            </h2>
            <Link
              href={`${basePath}/calendar`}
              className="inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:underline"
            >
              <CalendarIcon className="h-4 w-4" />
              {t('calendar.open')}
            </Link>
          </div>
          {failed ? (
            <FormBanner>{t('list.loadFailed')}</FormBanner>
          ) : spaces === null ? (
            <p role="status" className="text-body-md text-on-surface-variant">
              {t('loading')}
            </p>
          ) : spaces.length === 0 ? (
            <p className="rounded border border-dashed border-outline-variant px-4 py-6 text-body-md text-on-surface-variant">
              {t(`${role}.empty`)}
            </p>
          ) : (
            <ul className="space-y-3">
              {spaces.map((space) => (
                <li key={space.id}>
                  <ClassroomCard space={space} href={`${basePath}/${space.id}`} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <div>{form}</div>
      </div>
    </>
  )
}

function ClassroomCard({ space, href }: { space: SpaceSummary; href: string }) {
  const t = useTranslations('classroom.card')
  return (
    <Link
      href={href}
      className="flex items-center gap-4 rounded-xl border border-outline-variant bg-surface-container-lowest p-5 shadow-sm transition-colors hover:bg-surface-container-low"
    >
      <span
        aria-hidden="true"
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary-container"
      >
        <BookIcon className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-grow">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate font-headline text-body-lg text-on-surface">
            {space.title}
          </span>
          {space.status === 'archived' && (
            <span className="rounded-full bg-surface-variant px-2 py-0.5 text-label-caps uppercase text-on-surface-variant">
              {t('archived')}
            </span>
          )}
        </span>
        <span className="block text-body-sm text-on-surface-variant">
          {t('subjectLine', {
            subject: space.subject.name,
            classLevel: space.subject.class_level,
            board: space.subject.board,
          })}
        </span>
        <span className="block text-body-sm text-on-surface-variant">
          {space.viewer_role === 'owner'
            ? t('members', { count: space.member_count ?? 0 })
            : t('teacher', { name: space.owner_name ?? t('unnamedTeacher') })}
        </span>
      </span>
      <ArrowIcon className="h-5 w-5 shrink-0 text-on-surface-variant rtl:-scale-x-100" />
    </Link>
  )
}
