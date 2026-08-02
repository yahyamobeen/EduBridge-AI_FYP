'use client'

import { useTranslations } from 'next-intl'
import { DashboardShell, PlaceholderCard } from '@/components/app/DashboardShell'
import { SessionGuard } from '@/components/app/SessionGuard'
import type { MeResponse } from '@/lib/api/types'

/**
 * The three role dashboards.
 *
 * They are SHELLS. No dashboard data endpoint exists in the contract (plan
 * assumption A3), so the panels name what will live there and say plainly that
 * it is not available yet, instead of rendering the mockups' invented 78% exam
 * readiness and 62% syllabus coverage. Fabricated analytics have a way of
 * surviving into a demo and then into a report.
 *
 * What IS real here is the navigation and the role boundary, which is the part
 * with security consequences.
 */

function classSummary(me: MeResponse): string {
  const profile = me.profile
  if (profile === null) return me.email
  // `class_level` is a number and `student_group` a code; both come straight
  // from the profile rather than being re-derived here.
  return `${profile.board} · ${profile.class_level} · ${profile.student_group}`
}

export function StudentDashboard() {
  const t = useTranslations('dashboard.student')
  const tc = useTranslations('dashboard.cards')

  return (
    <SessionGuard allow={['student']}>
      {(me) => (
        <DashboardShell me={me} subtitle={classSummary(me)}>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: me.full_name.split(' ')[0] ?? me.full_name })}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </header>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
            <PlaceholderCard
              span={8}
              title={tc('performanceTitle')}
              body={tc('performanceBody')}
            />
            <PlaceholderCard span={4} title={tc('studyNextTitle')} body={tc('studyNextBody')} />
            <PlaceholderCard
              span={4}
              title={tc('tutorTitle')}
              body={tc('tutorBody')}
              href="/coming-soon/tutor"
            />
            <PlaceholderCard span={4} title={tc('quizzesTitle')} body={tc('quizzesBody')} />
            {/*
              prd.md §4.2 guarantees a student can see who may view them and can
              leave any space. The right needs a route, so it has a card too.
            */}
            <PlaceholderCard
              span={4}
              title={tc('myClassesTitle')}
              body={tc('myClassesBody')}
              href="/coming-soon/my-classes"
            />
          </div>
        </DashboardShell>
      )}
    </SessionGuard>
  )
}

export function TeacherDashboard() {
  const t = useTranslations('dashboard.teacher')
  const tc = useTranslations('dashboard.cards')

  return (
    <SessionGuard allow={['teacher']}>
      {(me) => (
        <DashboardShell me={me} subtitle={t('role')}>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: me.full_name.split(' ')[0] ?? me.full_name })}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </header>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
            <PlaceholderCard span={8} title={tc('spacesTitle')} body={tc('spacesBody')} />
            <PlaceholderCard span={4} title={tc('rosterTitle')} body={tc('rosterBody')} />
            {/* Subject-scoped only: there is no teacher-wide weekly report. */}
            <PlaceholderCard span={6} title={tc('reportsTitle')} body={tc('reportsBody')} />
            <PlaceholderCard span={6} title={tc('sloTitle')} body={tc('sloBody')} />
          </div>
        </DashboardShell>
      )}
    </SessionGuard>
  )
}

export function ParentDashboard() {
  const t = useTranslations('dashboard.parent')
  const tc = useTranslations('dashboard.cards')

  return (
    <SessionGuard allow={['parent']}>
      {(me) => (
        <DashboardShell me={me} subtitle={t('role')}>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: me.full_name.split(' ')[0] ?? me.full_name })}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </header>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
            <PlaceholderCard
              span={8}
              title={tc('childProgressTitle')}
              body={tc('childProgressBody')}
            />
            <PlaceholderCard span={4} title={tc('howToHelpTitle')} body={tc('howToHelpBody')} />

            {/*
              Stated, not implied. prd.md §4.2 forbids a parent reading chat
              content, and the mockup's "Play Session" button advertised exactly
              that capability. Saying so out loud is what keeps someone from
              "restoring" it as a missing feature.
            */}
            <section className="col-span-1 rounded-md border border-secondary/30 bg-secondary-container/40 p-6 md:col-span-12">
              <h3 className="mb-2 font-headline text-headline-md text-on-secondary-container">
                {tc('privacyTitle')}
              </h3>
              <p className="text-body-md text-on-surface">{tc('privacyBody')}</p>
            </section>
          </div>
        </DashboardShell>
      )}
    </SessionGuard>
  )
}
