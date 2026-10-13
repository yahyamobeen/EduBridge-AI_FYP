/**
 * Month-grid arithmetic for the classroom calendar — pure, so it is tested
 * without rendering anything.
 *
 * Every date here is LOCAL: the grid is the user's wall calendar, and the API
 * range is the pair of instants at its edges. `new Date(y, m, d)` also absorbs
 * month and year overflow (day 0, day 32, month 12), which is what keeps the
 * arithmetic below free of special cases.
 */

/** 6 × 7 days covering `month` (0-based), weeks starting on Monday (ISO). */
export function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7 // Monday = 0 … Sunday = 6
  return Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - offset + i))
}

/** The API range for a grid: its first local midnight to the local midnight after its last day. */
export function gridRange(days: Date[]): { from: string; to: string } {
  const first = days[0]!
  const last = days[days.length - 1]!
  return {
    from: first.toISOString(),
    to: new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1).toISOString(),
  }
}

/** The same local day, as a map key. */
export const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`

/** `delta` months from a year and 0-based month. */
export function addMonths(
  year: number,
  month: number,
  delta: number,
): { year: number; month: number } {
  const d = new Date(year, month + delta, 1)
  return { year: d.getFullYear(), month: d.getMonth() }
}
