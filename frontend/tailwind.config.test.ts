import { describe, expect, it } from 'vitest'
import config from './tailwind.config'

/**
 * These assertions pin the two DESIGN.md conflicts that were resolved by
 * decision rather than by reading (tdd.md §14.3, decisions 12 and 13). Both are
 * the kind of thing a later "tidy-up" silently reverts, and neither would fail
 * a build or a type check -- it would just quietly render the wrong product.
 */

const theme = config.theme?.extend
const colors = theme?.colors as Record<string, string>
const radii = theme?.borderRadius as Record<string, string>
const sizes = theme?.fontSize as Record<string, [string, Record<string, string>]>

describe('colour tokens', () => {
  it('uses the DESIGN.md frontmatter values, not the prose ones', () => {
    // The prose cites #1A56DB / #059669 / #7C3AED. Those are the -container
    // variants, not the base roles. Frontmatter wins (decision 13).
    expect(colors.primary).toBe('#003fb1')
    expect(colors.secondary).toBe('#006c4a')
    expect(colors.tertiary).toBe('#5d00cc')
    expect(colors['primary-container']).toBe('#1a56db')
  })

  it('defines the role themes and security states', () => {
    expect(colors['student-blue']).toBe('#EBF5FF')
    expect(colors['teacher-indigo']).toBe('#4F46E5')
    expect(colors['status-verified']).toBe('#10B981')
    expect(colors['status-quarantined']).toBe('#EF4444')
    expect(colors['status-pending']).toBe('#F59E0B')
  })
})

describe('radius scale', () => {
  it('follows the frontmatter, so mockup class names must be remapped', () => {
    // A mockup button is `rounded-lg` at 0.5rem. Here `lg` is 1rem and 0.5rem
    // is DEFAULT, so copying the class verbatim doubles the corner radius.
    expect(radii.DEFAULT).toBe('0.5rem')
    expect(radii.lg).toBe('1rem')
    expect(radii.md).toBe('0.75rem')
    expect(radii.full).toBe('9999px')
  })
})

describe('Urdu typography', () => {
  it('gives Urdu at least 1.8x line height so diacritics do not collide', () => {
    for (const key of ['urdu-text-lg', 'urdu-text-md'] as const) {
      const entry = sizes[key]
      expect(entry, `${key} must be defined`).toBeDefined()
      const [size, meta] = entry!
      const ratio = parseFloat(meta.lineHeight!) / parseFloat(size)
      expect(ratio, `${key} line-height ratio`).toBeGreaterThanOrEqual(1.8)
    }
  })
})
