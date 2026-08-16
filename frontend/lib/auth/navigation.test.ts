import { describe, expect, it } from 'vitest'
import en from '@/messages/en.json'
import type { Role } from '@/lib/api/types'
import { NAV_BY_ROLE, navFor } from './navigation'

const ROLES: Role[] = ['student', 'teacher', 'parent', 'admin']

/**
 * THE HIGHEST-VALUE REGRESSION TEST IN THE FRONTEND.
 *
 * The supplied mockups shipped one student sidebar pasted into all three
 * dashboards, which handed a parent a button that replays their child's AI
 * tutor conversation. `prd.md` §4.2 forbids a parent reading chat content and
 * `GET /api/tutor/sessions/{id}` is student-owner-only, so that control was a
 * privacy violation rather than a dead link.
 *
 * A future copy-paste would reintroduce it silently. This asserts it cannot.
 */
describe('the parent surface is read-only', () => {
  const parentHrefs = navFor('parent').map((i) => i.href.toLowerCase())
  const parentKeys = navFor('parent').map((i) => i.key.toLowerCase())

  it.each([
    ['tutor', /tutor/],
    ['session replay', /session|replay|play/],
    ['study planner', /planner/],
    ['practice', /practice/],
    ['quizzes', /quiz/],
    ['subjects', /subject|curriculum/],
  ])('exposes no %s control', (_label, pattern) => {
    expect(parentHrefs.filter((h) => pattern.test(h))).toEqual([])
    expect(parentKeys.filter((k) => pattern.test(k))).toEqual([])
  })
})

describe('the teacher surface', () => {
  it('has no tutor entry, matching the scope of /api/tutor/ask', () => {
    // prd.md §4.2 once granted teachers tutor access "for own testing" while
    // the endpoint has always been student-scoped. Decision 17 resolved it.
    expect(navFor('teacher').filter((i) => /tutor/i.test(i.key))).toEqual([])
  })

  it('offers reports, which are subject-scoped rather than platform-wide', () => {
    expect(navFor('teacher').some((i) => i.key === 'reports')).toBe(true)
  })
})

describe('the student surface', () => {
  it('exposes My Classes, because the right to leave a space needs a route', () => {
    // prd.md §4.2 guarantees a student can see who may view them and can leave
    // any space at any time. No mockup had an entry for it.
    expect(navFor('student').some((i) => i.key === 'myClasses')).toBe(true)
  })
})

describe('the map itself', () => {
  it('covers every role', () => {
    for (const role of ROLES) expect(navFor(role).length).toBeGreaterThan(0)
  })

  it('sends each role to its own dashboard first', () => {
    expect(navFor('student')[0]?.href).toBe('/dashboard')
    expect(navFor('teacher')[0]?.href).toBe('/teacher')
    expect(navFor('parent')[0]?.href).toBe('/parent')
    // `admin` was missing here while the href test below allow-listed it, so
    // NEITHER test covered the admin row — which is how finding A6 survived: the
    // role routes to /admin, and no such page exists. The page is built in
    // phase 1b; this assertion is the one that should have caught it.
    expect(navFor('admin')[0]?.href).toBe('/admin')
  })

  it('gives every item a translated label in all three locales', async () => {
    const locales = ['en', 'ur', 'ur-Latn'] as const
    const keys = new Set(
      Object.values(NAV_BY_ROLE)
        .flat()
        .map((i) => i.key),
    )

    for (const locale of locales) {
      const messages = (await import(`@/messages/${locale}.json`)).default as typeof en
      for (const key of keys) {
        expect(messages.nav.items, `${locale}/${key}`).toHaveProperty(key)
      }
    }
  })

  it('routes every non-dashboard item somewhere that exists', () => {
    // Each must be either a built route or a coming-soon slug; `href="#"` and
    // bare paths that 404 are both regressions.
    for (const item of Object.values(NAV_BY_ROLE).flat()) {
      expect(item.href, item.key).toMatch(/^\/(dashboard|teacher|parent|admin|coming-soon\/)/)
    }
  })
})
