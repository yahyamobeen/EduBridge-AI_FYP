import type { Role } from '@/lib/api/types'

/**
 * Navigation, derived per role from the `prd.md` §4.2 RBAC matrix.
 *
 * THIS FILE IS AN RBAC BOUNDARY, not a styling concern. Every entry was checked
 * against the `tdd.md` §3.1 endpoint tables before being listed, and three of
 * the decisions it encodes are ones a shared component tree makes very easy to
 * get wrong:
 *
 *  (a) THE PARENT SURFACE IS READ-ONLY and exposes no tutor, no chat replay and
 *      no planner write. The supplied mockups shipped ONE student sidebar
 *      pasted into all three dashboards, which handed parents a "Play Session"
 *      button that replays a child's AI tutor conversation. `GET
 *      /api/tutor/sessions/{id}` is student-owner-only and the matrix says a
 *      parent may never read chat content — so that control was not a dead
 *      link, it was a privacy violation with a button on it.
 *
 *  (b) THE TEACHER SURFACE HAS NO TUTOR ENTRY. `prd.md` §4.2 used to grant
 *      teachers tutor access "for own testing" while `POST /api/tutor/ask` has
 *      always been scoped to gate-verified students. The TDD won (decision 17).
 *
 *  (c) THE STUDENT SURFACE MUST EXPOSE MY CLASSES. `prd.md` §4.2 guarantees a
 *      student can see who is able to view them and can leave any space at any
 *      time. No mockup had an entry for it, and a right with no route to it is
 *      not a right.
 *
 * Building every sidebar from this one map is what makes it impossible for an
 * item to leak across roles by copy-paste. A test asserts the parent nav
 * contains none of the forbidden controls.
 */

export type NavItem = {
  /** Message key under `nav.items`. */
  key: string
  href: string
}

const SETTINGS: NavItem[] = [
  { key: 'settings', href: '/coming-soon/settings' },
  { key: 'help', href: '/coming-soon/help' },
]

export const NAV_BY_ROLE: Record<Role, NavItem[]> = {
  student: [
    { key: 'dashboard', href: '/dashboard' },
    { key: 'subjects', href: '/coming-soon/curriculum' },
    { key: 'tutor', href: '/coming-soon/tutor' },
    { key: 'practice', href: '/coming-soon/practice' },
    { key: 'quizzes', href: '/coming-soon/quizzes' },
    { key: 'progress', href: '/coming-soon/progress' },
    { key: 'myClasses', href: '/coming-soon/my-classes' },
    { key: 'planner', href: '/coming-soon/planner' },
    ...SETTINGS,
  ],
  teacher: [
    { key: 'dashboard', href: '/teacher' },
    { key: 'mySpaces', href: '/coming-soon/spaces' },
    { key: 'quizzes', href: '/coming-soon/quizzes' },
    // Subject-scoped only: there is no /api/reports/weekly for teachers.
    { key: 'reports', href: '/coming-soon/reports' },
    { key: 'roster', href: '/coming-soon/roster' },
    { key: 'slo', href: '/coming-soon/slo' },
    { key: 'announcements', href: '/coming-soon/announcements' },
    ...SETTINGS,
  ],
  parent: [
    { key: 'dashboard', href: '/parent' },
    { key: 'myChild', href: '/coming-soon/my-child' },
    { key: 'progress', href: '/coming-soon/progress' },
    { key: 'howToHelp', href: '/coming-soon/how-to-help' },
    ...SETTINGS,
  ],
  /*
    prd.md FR-K1 names the administrator's four duties beyond the dashboard:
    "provisioning, curriculum, security/AgentSBOM, quotas, daily endpoint access
    logs (TEL-5)". Provisioning has no entry because it is not a self-service
    surface — an administrator is created by SQL run by the repository owner,
    and `app_user_insert` refuses `role = 'admin'` to the application role.

    NOTHING HERE READS CONVERSATION CONTENT, and nothing may be added that does:
    user-stories.md:286 requires this surface to "expose no path to conversation
    content", and the same paste-one-sidebar-into-every-dashboard mistake that
    handed parents a chat replay button would do far more damage here.
  */
  admin: [
    { key: 'dashboard', href: '/admin' },
    // Reuses the existing `curriculum` slug rather than adding an
    // admin-specific one. Checked by reading the rendered page: the heading is
    // "Curriculum is on the way", which is accurate for an administrator too,
    // whereas a new slug would fall through to the generic "In development" and
    // say strictly less. The page's "Create an account" call to action is
    // wrong for any signed-in user, of every role, and already reachable from
    // the Settings and Help entries every sidebar carries — pre-existing, and
    // not something this entry introduces.
    { key: 'curriculum', href: '/coming-soon/curriculum' },
    { key: 'security', href: '/coming-soon/security' },
    { key: 'quotas', href: '/coming-soon/quotas' },
    { key: 'endpointLogs', href: '/coming-soon/logs' },
    ...SETTINGS,
  ],
}

/** Role palettes from DESIGN.md's "Functional Color Logic". */
export const ROLE_ACCENT: Record<Role, string> = {
  student: 'text-primary',
  teacher: 'text-teacher-indigo',
  parent: 'text-secondary',
  admin: 'text-tertiary',
}

export function navFor(role: Role): NavItem[] {
  return NAV_BY_ROLE[role]
}
