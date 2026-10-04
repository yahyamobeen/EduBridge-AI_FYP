'use client'

import { useEffect, useMemo, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { DashboardShell } from '@/components/app/DashboardShell'
import { SessionGuard } from '@/components/app/SessionGuard'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowLeftIcon, ChevronRightIcon } from '@/components/ui/Icon'
import { Link } from '@/i18n/navigation'
import { getCalendar } from '@/lib/api/endpoints'
import type { CalendarItem, MeResponse } from '@/lib/api/types'
import { addMonths, dayKey, gridRange, monthGrid } from '@/lib/calendar'
import { StatusChip } from './AssignmentParts'
import { CARD, SECONDARY_BUTTON } from './styles'

/**
 * The classroom calendar — `/classroom/calendar` (student) and
 * `/teacher/classroom/calendar` (teacher), prd.md CL-9.
 *
 * Nothing here decides what may be shown: the server returns only what the
 * caller could already see (deadlines; and, for a teacher, their own posts that
 * are not live yet). This page lays it out on the user's own wall calendar —
 * local days, weeks from Monday — and links each entry back into its classroom.
 */
export function StudentCalendar() {
  return (
    <SessionGuard allow={['student']}>
      {(me) => <CalendarPage me={me} basePath="/classroom" />}
    </SessionGuard>
  )
}

export function TeacherCalendar() {
  return (
    <SessionGuard allow={['teacher']}>
      {(me) => <CalendarPage me={me} basePath="/teacher/classroom" />}
    </SessionGuard>
  )
}

function CalendarPage({ me, basePath }: { me: MeResponse; basePath: string }) {
  const t = useTranslations('classroom')
  const role = me.role === 'teacher' ? 'teacher' : 'student'
  return (
    <DashboardShell me={me} subtitle={t(`${role}.subtitle`)}>
      <Link
        href={basePath}
        className="mb-6 inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
        {t('detail.back')}
      </Link>
      <header className="mb-6">
        <h1 className="font-headline text-headline-lg text-on-background">
          {t('calendar.title')}
        </h1>
        <p className="text-body-md text-on-surface-variant">{t(`calendar.${role}Intro`)}</p>
      </header>
      <CalendarView basePath={basePath} />
    </DashboardShell>
  )
}

/** Month navigation and loading. `start` is injectable so tests pin the month. */
export function CalendarView({ basePath, start }: { basePath: string; start?: Date }) {
  const t = useTranslations('classroom.calendar')
  const format = useFormatter()
  const [initial] = useState(() => start ?? new Date())
  const [view, setView] = useState({ year: initial.getFullYear(), month: initial.getMonth() })
  const days = useMemo(() => monthGrid(view.year, view.month), [view])
  const key = `${view.year}-${view.month}`
  // Loading is derived from the key the data belongs to, so changing month
  // never needs a synchronous setState inside the effect.
  const [data, setData] = useState<{
    key: string
    items: CalendarItem[]
    truncated: boolean
  } | null>(null)
  const [failedKey, setFailedKey] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const { from, to } = gridRange(days)
    getCalendar(from, to, controller.signal)
      .then((r) => setData({ key, items: r.items, truncated: r.truncated }))
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailedKey(key)
      })
    return () => controller.abort()
  }, [days, key])

  const step = (delta: number) => setView((v) => addMonths(v.year, v.month, delta))
  const ready = data?.key === key
  const monthLabel = format.dateTime(new Date(view.year, view.month, 1), {
    month: 'long',
    year: 'numeric',
  })

  return (
    <section aria-labelledby="calendar-month" className={CARD}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id="calendar-month" className="font-headline text-headline-md text-on-surface">
          {monthLabel}
        </h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={SECONDARY_BUTTON}
            onClick={() => step(-1)}
            aria-label={t('previous')}
          >
            <ChevronRightIcon className="h-4 w-4 -scale-x-100 rtl:scale-x-100" />
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON}
            onClick={() => {
              const now = new Date()
              setView({ year: now.getFullYear(), month: now.getMonth() })
            }}
          >
            {t('today')}
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON}
            onClick={() => step(1)}
            aria-label={t('next')}
          >
            <ChevronRightIcon className="h-4 w-4 rtl:-scale-x-100" />
          </button>
        </div>
      </div>

      {failedKey === key && !ready ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : !ready ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : (
        <>
          {data.truncated && (
            <div className="mb-4">
              <FormBanner>{t('truncated')}</FormBanner>
            </div>
          )}
          {!data.items.some((i) => new Date(i.at).getMonth() === view.month) && (
            <p className="mb-4 text-body-md text-on-surface-variant">{t('empty')}</p>
          )}
          <CalendarMonth
            days={days}
            month={view.month}
            items={data.items}
            basePath={basePath}
          />
        </>
      )}
    </section>
  )
}

/**
 * One grid, two layouts: seven columns from `md` up; below that a list of
 * only the days that have entries. Same DOM either way, so a screen reader
 * hears each day's full date, not a bare number.
 */
export function CalendarMonth({
  days,
  month,
  items,
  basePath,
}: {
  days: Date[]
  month: number
  items: CalendarItem[]
  basePath: string
}) {
  const format = useFormatter()
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>()
    for (const item of items) {
      const k = dayKey(new Date(item.at))
      map.set(k, [...(map.get(k) ?? []), item])
    }
    return map
  }, [items])
  const todayKey = dayKey(new Date())

  return (
    <div>
      <div aria-hidden="true" className="mb-1 hidden grid-cols-7 gap-1 md:grid">
        {days.slice(0, 7).map((d) => (
          <span
            key={d.toISOString()}
            className="px-2 text-label-caps uppercase text-on-surface-variant"
          >
            {format.dateTime(d, { weekday: 'short' })}
          </span>
        ))}
      </div>
      <ol className="grid grid-cols-1 gap-2 md:grid-cols-7 md:gap-1">
        {days.map((d) => {
          const k = dayKey(d)
          const entries = byDay.get(k) ?? []
          const inMonth = d.getMonth() === month
          return (
            <li
              key={k}
              className={`rounded border border-outline-variant p-2 md:min-h-[6rem] ${
                entries.length === 0 ? 'hidden md:block' : ''
              } ${inMonth ? '' : 'bg-surface-variant/30'}`}
            >
              <h3
                className={`mb-1 text-body-sm ${
                  k === todayKey ? 'font-semibold text-primary' : 'text-on-surface-variant'
                } ${inMonth ? '' : 'opacity-70'}`}
              >
                <span className="sr-only">{format.dateTime(d, { dateStyle: 'full' })}</span>
                <span aria-hidden="true" className="md:hidden">
                  {format.dateTime(d, { weekday: 'long', day: 'numeric', month: 'long' })}
                </span>
                <span aria-hidden="true" className="hidden md:inline">
                  {format.number(d.getDate())}
                </span>
              </h3>
              {entries.length > 0 && (
                <ul className="space-y-1">
                  {entries.map((item) => (
                    <li key={`${item.kind}-${item.ref_id}`}>
                      <Entry item={item} basePath={basePath} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

const KIND_STYLE: Record<CalendarItem['kind'], string> = {
  due: 'border-primary',
  scheduled_assignment: 'border-secondary border-dashed',
  scheduled_announcement: 'border-secondary border-dashed',
}

function Entry({ item, basePath }: { item: CalendarItem; basePath: string }) {
  const t = useTranslations('classroom.calendar')
  const format = useFormatter()
  // An assignment opens in its classroom's Classwork tab; an announcement in
  // the Stream, which is where a classroom opens anyway.
  const href =
    item.kind === 'scheduled_announcement'
      ? `${basePath}/${item.space_id}`
      : `${basePath}/${item.space_id}?assignment=${item.ref_id}`
  const label = {
    due: t('due'),
    scheduled_assignment: t('scheduledAssignment'),
    scheduled_announcement: t('scheduledAnnouncement'),
  }[item.kind]

  return (
    <Link
      href={href}
      className={`block rounded border-s-4 bg-surface-container px-2 py-1 text-body-sm hover:bg-surface-container-high ${KIND_STYLE[item.kind]}`}
    >
      <span className="block text-on-surface-variant">
        {format.dateTime(new Date(item.at), { timeStyle: 'short' })} · {label}
      </span>
      <span className="block break-words font-semibold text-on-surface">{item.title}</span>
      <span className="block text-on-surface-variant">{item.space_title}</span>
      {item.my_status && (
        <span className="mt-1 block">
          <StatusChip status={item.my_status} />
        </span>
      )}
    </Link>
  )
}
