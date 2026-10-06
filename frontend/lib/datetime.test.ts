import { describe, expect, it } from 'vitest'
import { isoToLocalInput, localInputToIso, nowLocalInput } from './datetime'

describe('datetime-local ⇄ ISO instant', () => {
  it('reads the input as local wall time and produces an instant with an offset', () => {
    const iso = localInputToIso('2026-10-05T14:30')
    expect(iso).toMatch(/Z$/)
    // Same wall-clock reading back, whatever zone the test runs in.
    expect(isoToLocalInput(iso)).toBe('2026-10-05T14:30')
  })

  it('formats the current minute for an input `min`', () => {
    expect(nowLocalInput()).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
  })
})
