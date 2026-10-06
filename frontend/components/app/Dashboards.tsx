'use client'

import { useTranslations } from 'next-intl'
import { ClassroomsCard } from '@/components/app/ClassroomsCard'
import { PlaceholderCard } from '@/components/app/DashboardShell'
import { RequireRole } from '@/components/app/SessionGuard'
import { firstName } from '@/lib/auth/displayName'

/**
 * The four role dashboards.
 *
 * They are SHELLS. No dashboard data endpoint exists in the contract (plan
 * assumption A3), so the panels name what will live there and say plainly that
 * it is not available yet, instead of rendering the mockups' invented 78% exam
 * readiness and 62% syllabus coverage. Fabricated analytics have a way of
 * surviving into a demo and then into a report.
 *
 * What IS real here is the navigation and the role boundary, which is the part
 * with security consequences — and, since classroom Phase 6c, the classroom
 * card (`ClassroomsCard`), which lists the caller's real classrooms: that
 * feature exists, so its card must not say otherwise.
 */

export function StudentDashboard() {
  const t = useTranslations('dashboard.student')
  const tc = useTranslations('dashboard.cards')

  return (
    <RequireRole allow={['student']}>
      {(me) => (
        <>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: firstName(me) })}
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
            <ClassroomsCard role="student" span={4} />
          </div>
        </>
      )}
    </RequireRole>
  )
}

export function TeacherDashboard() {
  const t = useTranslations('dashboard.teacher')
  const tc = useTranslations('dashboard.cards')

  return (
    <RequireRole allow={['teacher']}>
      {(me) => (
        <>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: firstName(me) })}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </header>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
            {/* The whole row: each classroom's People tab is the roster, so the
                "Class roster" placeholder that sat here was removed (2026-10-06). */}
            <ClassroomsCard role="teacher" span={12} />
            {/* Subject-scoped only: there is no teacher-wide weekly report. */}
            <PlaceholderCard span={6} title={tc('reportsTitle')} body={tc('reportsBody')} />
            <PlaceholderCard span={6} title={tc('sloTitle')} body={tc('sloBody')} />
          </div>
        </>
      )}
    </RequireRole>
  )
}

export function ParentDashboard() {
  const t = useTranslations('dashboard.parent')
  const tc = useTranslations('dashboard.cards')

  return (
    <RequireRole allow={['parent']}>
      {(me) => (
        <>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: firstName(me) })}
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
        </>
      )}
    </RequireRole>
  )
}

export function AdminDashboard() {
  const t = useTranslations('dashboard.admin')
  const tc = useTranslations('dashboard.cards')

  return (
    <RequireRole allow={['admin']}>
      {(me) => (
        <>
          <header className="mb-8">
            <h1 className="font-headline text-headline-lg text-on-background">
              {t('welcome', { name: firstName(me) })}
            </h1>
            <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
          </header>

          {/*
            The five panels are prd.md FR-K1's five duties, one to one:
            "provisioning, curriculum, security/AgentSBOM, quotas, daily
            endpoint access logs (TEL-5)". None of the eight /api/admin/*
            endpoints in tdd.md §3.1 exists yet, so these name what will live
            here rather than rendering invented figures — the same rule the
            other three dashboards follow.
          */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
            <PlaceholderCard
              span={6}
              title={tc('provisioningTitle')}
              body={tc('provisioningBody')}
            />
            <PlaceholderCard
              span={6}
              title={tc('curriculumAdminTitle')}
              body={tc('curriculumAdminBody')}
              href="/coming-soon/curriculum"
            />
            <PlaceholderCard
              span={6}
              title={tc('securityTitle')}
              body={tc('securityBody')}
              href="/coming-soon/security"
            />
            <PlaceholderCard
              span={6}
              title={tc('quotasTitle')}
              body={tc('quotasBody')}
              href="/coming-soon/quotas"
            />
            <PlaceholderCard
              span={12}
              title={tc('endpointLogsTitle')}
              body={tc('endpointLogsBody')}
              href="/coming-soon/logs"
            />

            {/*
              STATED, NOT IMPLIED — the same reasoning as the parent panel above.
              user-stories.md:286 requires that the administrator surface "expose
              no path to conversation content", and the card's failure criterion
              is an administrator reading it. prd.md TEL-3 says the same about
              telemetry: metadata, never message bodies. Writing it on the page
              is what stops a future contributor adding a "view session" control
              here and believing it to be a missing feature.
            */}
            <section className="col-span-1 rounded-md border-s-4 border-tertiary bg-tertiary-container/30 p-6 md:col-span-12">
              <h3 className="mb-2 font-headline text-headline-md text-on-tertiary-container">
                {tc('adminPrivacyTitle')}
              </h3>
              <p className="text-body-md text-on-surface">{tc('adminPrivacyBody')}</p>
            </section>
          </div>
        </>
      )}
    </RequireRole>
  )
}
