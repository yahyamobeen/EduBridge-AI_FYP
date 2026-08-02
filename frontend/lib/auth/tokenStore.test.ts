import { beforeEach, describe, expect, it } from 'vitest'
import {
  __resetTokenStoreForTests,
  clearAccessToken,
  getAccessToken,
  hasAccessToken,
  isExpired,
  setAccessToken,
  shouldRefreshAhead,
} from './tokenStore'

const LIFETIME = 900 // the contract's expires_in

beforeEach(() => {
  __resetTokenStoreForTests()
})

describe('token storage', () => {
  it('holds the token in memory and hands it back', () => {
    setAccessToken('abc', LIFETIME)
    expect(getAccessToken()).toBe('abc')
    expect(hasAccessToken()).toBe(true)
  })

  it('never writes the token to browser storage', () => {
    // The whole point of the in-memory store: nothing survives the tab, and
    // injected script has nothing to read (tdd.md §6.11).
    setAccessToken('secret-token', LIFETIME)
    expect(window.localStorage.getItem('secret-token')).toBeNull()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(document.cookie).not.toContain('secret-token')
  })

  it('clears completely on sign-out', () => {
    setAccessToken('abc', LIFETIME)
    clearAccessToken()
    expect(getAccessToken()).toBeNull()
    expect(hasAccessToken()).toBe(false)
  })
})

describe('proactive refresh', () => {
  it('does not refresh a freshly issued token', () => {
    const now = Date.now()
    setAccessToken('abc', LIFETIME)
    expect(shouldRefreshAhead(LIFETIME, now)).toBe(false)
  })

  it('does not refresh at half life', () => {
    const now = Date.now()
    setAccessToken('abc', LIFETIME)
    expect(shouldRefreshAhead(LIFETIME, now + LIFETIME * 500)).toBe(false)
  })

  it('refreshes once past 80 percent of the lifetime, before anything fails', () => {
    // Waiting for a 401 instead would interrupt a student mid-form.
    const now = Date.now()
    setAccessToken('abc', LIFETIME)
    expect(shouldRefreshAhead(LIFETIME, now + LIFETIME * 1000 * 0.81)).toBe(true)
  })

  it('reports nothing to refresh when there is no token', () => {
    expect(shouldRefreshAhead(LIFETIME)).toBe(false)
  })
})

describe('expiry', () => {
  it('is not expired while within the lifetime', () => {
    setAccessToken('abc', LIFETIME)
    expect(isExpired()).toBe(false)
  })

  it('is expired once the lifetime has passed', () => {
    const now = Date.now()
    setAccessToken('abc', LIFETIME)
    expect(isExpired(now + LIFETIME * 1000 + 1)).toBe(true)
  })
})
