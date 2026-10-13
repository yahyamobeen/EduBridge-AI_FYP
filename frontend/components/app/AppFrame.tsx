'use client'

import type { ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { DashboardShell } from '@/components/app/DashboardShell'
import { SessionGuard } from '@/components/app/SessionGuard'
import type { MeResponse } from '@/lib/api/types'

/**
 * The authenticated application's frame, rendered once by the `(app)` layout:
 * the identity check and the sidebar, kept mounted while the pages change
 * inside them (classroom Phase 6c). Each page still declares its own roles
 * with `RequireRole`.
 */
export function AppFrame({ children }: { children: ReactNode }) {
  return <SessionGuard>{(me) => <Framed me={me}>{children}</Framed>}</SessionGuard>
}

function Framed({ me, children }: { me: MeResponse; children: ReactNode }) {
  const t = useTranslations('dashboard')
  // The line under the name: one per user, not one per page. A student's
  // board, class and group; anyone else's role.
  const subtitle = me.role === 'student' ? classSummary(me) : t(`${me.role}.role`)
  return (
    <DashboardShell me={me} subtitle={subtitle}>
      {children}
    </DashboardShell>
  )
}

function classSummary(me: MeResponse): string {
  const profile = me.profile
  if (profile === null) return me.email
  // `class_level` is a number and `student_group` a code; both come straight
  // from the profile rather than being re-derived here.
  return `${profile.board} · ${profile.class_level} · ${profile.student_group}`
}
