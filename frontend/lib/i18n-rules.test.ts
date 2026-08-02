import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The RTL rule, enforced instead of remembered.
 *
 * `ur` is the only right-to-left locale (prd.md I18N-4), and mirroring is
 * achieved with LOGICAL properties — `ms`/`me`, `ps`/`pe`, `start`/`end`,
 * `text-start`/`text-end` — so a new screen is correct by construction. A
 * single `ml-2` looks fine in English and silently breaks the Urdu layout,
 * which nobody notices until someone reads the page in Urdu.
 *
 * The prototypes are entirely physical (`pl-10`, `left-0`, `text-left`), so
 * this catches a class copied straight across.
 */

const ROOTS = ['app', 'components']

/** `left-0`, `ml-4`, `pr-3`, `text-left`, `border-l`, `rounded-l-md`, … */
const PHYSICAL =
  /(?:^|[\s"'`:[])(?:-)?(?:ml|mr|pl|pr|left|right|border-l|border-r|rounded-l|rounded-r)(?:-[a-z0-9./[\]%-]+)?(?=[\s"'`\]]|$)|text-(?:left|right)/

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
  })
}

const files = ROOTS.flatMap((root) => walk(root))

describe('RTL correctness', () => {
  it('finds source files to check', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it.each(files)('%s uses logical properties, not physical ones', (file) => {
    const offending = readFileSync(file, 'utf8')
      .split('\n')
      .map((line, index) => ({ line, number: index + 1 }))
      // Only class strings matter; prose in a comment may say "left".
      .filter(({ line }) => /className|class=/.test(line))
      .filter(({ line }) => PHYSICAL.test(line))
      .map(({ line, number }) => `${number}: ${line.trim()}`)

    expect(offending, `use ms/me/ps/pe/start/end in ${file}`).toEqual([])
  })
})
