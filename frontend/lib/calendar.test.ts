import { describe, expect, it } from 'vitest'
import { addMonths, dayKey, gridRange, monthGrid } from './calendar'

/**
 * Written against LOCAL getters, so the assertions hold in whatever time zone
 * the test machine is in — which is the point: the grid is the user's own
 * wall calendar, never UTC's.
 */

const ymd = (d: Date) => [d.getFullYear(), d.getMonth() + 1, d.getDate()]

describe('monthGrid', () => {
  it('covers October 2026 in six Monday-first weeks', () => {
    const days = monthGrid(2026, 9)
    expect(days).toHaveLength(42)
    expect(ymd(days[0]!)).toEqual([2026, 9, 28]) // Monday 28 September
    expect(days[0]!.getDay()).toBe(1)
    expect(ymd(days[41]!)).toEqual([2026, 11, 8]) // Sunday 8 November
    expect(days.filter((d) => d.getMonth() === 9)).toHaveLength(31)
  })

  it('starts on the 1st when the month starts on a Monday', () => {
    expect(ymd(monthGrid(2026, 5)[0]!)).toEqual([2026, 6, 1]) // 1 June 2026 is a Monday
  })

  it('reaches back a whole week when the month starts on a Sunday', () => {
    const days = monthGrid(2026, 1) // 1 February 2026 is a Sunday
    expect(ymd(days[0]!)).toEqual([2026, 1, 26])
    expect(ymd(days[6]!)).toEqual([2026, 2, 1])
  })
})

describe('gridRange', () => {
  it('runs from the first local midnight to the midnight after the last day', () => {
    const days = monthGrid(2026, 9)
    const { from, to } = gridRange(days)
    const start = new Date(from)
    const end = new Date(to)
    expect(ymd(start)).toEqual([2026, 9, 28])
    expect([start.getHours(), start.getMinutes()]).toEqual([0, 0])
    expect(ymd(end)).toEqual([2026, 11, 9])
    expect([end.getHours(), end.getMinutes()]).toEqual([0, 0])
    expect(from).toMatch(/Z$/)
  })

  it('stays inside the 62-day limit the API enforces', () => {
    const { from, to } = gridRange(monthGrid(2026, 9))
    const days = (Date.parse(to) - Date.parse(from)) / 86_400_000
    expect(days).toBeLessThanOrEqual(62)
  })
})

describe('addMonths and dayKey', () => {
  it('wraps across years in both directions', () => {
    expect(addMonths(2026, 11, 1)).toEqual({ year: 2027, month: 0 })
    expect(addMonths(2026, 0, -1)).toEqual({ year: 2025, month: 11 })
  })

  it('treats two times on the same local day as one day', () => {
    expect(dayKey(new Date(2026, 9, 5, 0, 1))).toBe(dayKey(new Date(2026, 9, 5, 23, 59)))
    expect(dayKey(new Date(2026, 9, 5))).not.toBe(dayKey(new Date(2026, 9, 6)))
  })
})
