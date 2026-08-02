import { beforeEach, describe, expect, it } from 'vitest'
import {
  __resetChallengesForTests,
  clearAllChallenges,
  getEnrollmentHandoff,
  getPendingChallenge,
  getUnverifiedEmail,
  setEnrollmentHandoff,
  setPendingChallenge,
  setUnverifiedEmail,
} from './challenge'

beforeEach(() => {
  __resetChallengesForTests()
})

describe('challenge storage', () => {
  it('starts empty, so a screen opened directly has nothing to act on', () => {
    expect(getPendingChallenge()).toBeNull()
    expect(getEnrollmentHandoff()).toBeNull()
    expect(getUnverifiedEmail()).toBeNull()
  })

  it('round-trips a pending challenge with its server-chosen method', () => {
    setPendingChallenge({
      token: 'pending-1',
      method: 'email_otp',
      expiresAtMs: 1_000,
      email: 'aisha@example.com',
    })
    expect(getPendingChallenge()).toEqual({
      token: 'pending-1',
      method: 'email_otp',
      expiresAtMs: 1_000,
      email: 'aisha@example.com',
    })
  })

  it('drops every credential once a session exists, so none can be replayed', () => {
    setPendingChallenge({
      token: 'pending-1',
      method: 'totp',
      expiresAtMs: 1_000,
      email: 'a@example.com',
    })
    setEnrollmentHandoff({ token: 'enroll-1', expiresAtMs: 1_000, email: 'a@example.com' })
    setUnverifiedEmail('a@example.com')

    clearAllChallenges()

    expect(getPendingChallenge()).toBeNull()
    expect(getEnrollmentHandoff()).toBeNull()
    expect(getUnverifiedEmail()).toBeNull()
  })
})

/**
 * The rule these credentials exist to satisfy. A `pending_token` completes an
 * authentication step, so it follows the access token's storage rule exactly:
 * memory only, never anywhere that survives the tab (tdd.md §6.11).
 */
describe('storage rule', () => {
  it('writes nothing to web storage', () => {
    setPendingChallenge({
      token: 'pending-secret',
      method: 'totp',
      expiresAtMs: 1_000,
      email: 'a@example.com',
    })
    setEnrollmentHandoff({ token: 'enroll-secret', expiresAtMs: 1_000, email: 'a@example.com' })

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(document.cookie).not.toContain('pending-secret')
  })
})
