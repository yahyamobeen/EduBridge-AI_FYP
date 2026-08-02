import { describe, expect, it } from 'vitest'
import { ApiError, isRefreshableAuthError, toApiError } from './errors'

describe('toApiError', () => {
  it('reads the contract envelope', () => {
    const error = toApiError(400, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Bad input',
        details: { fields: { email: 'Already in use' } },
      },
    })
    expect(error.status).toBe(400)
    expect(error.code).toBe('VALIDATION_ERROR')
    expect(error.fieldErrors()).toEqual({ email: 'Already in use' })
    expect(error.isKnown()).toBe(true)
  })

  it('still produces an ApiError when the body is not an envelope', () => {
    // A proxy or a crash can return HTML or nothing at all. No screen should
    // have to special-case that, and none should render blank.
    for (const body of [null, '<html>502</html>', {}, { error: {} }]) {
      const error = toApiError(502, body)
      expect(error).toBeInstanceOf(ApiError)
      expect(error.message).toBeTruthy()
      expect(error.isKnown()).toBe(false)
    }
  })
})

describe('isRefreshableAuthError', () => {
  it('refreshes on an expired access token', () => {
    expect(isRefreshableAuthError(new ApiError(401, 'UNAUTHENTICATED', 'x'))).toBe(true)
  })

  /**
   * The highest-value assertion in this file. Both codes below are 401s, so a
   * status-based check would retry them -- resubmitting a code the user already
   * got wrong and consuming one of their limited attempts before lockout.
   */
  it('does NOT retry a wrong two-factor code', () => {
    expect(isRefreshableAuthError(new ApiError(401, 'TWO_FACTOR_INVALID', 'x'))).toBe(false)
  })

  it('does NOT retry an expired two-factor challenge', () => {
    expect(isRefreshableAuthError(new ApiError(401, 'PENDING_TOKEN_EXPIRED', 'x'))).toBe(false)
  })

  it('ignores errors that are not 401', () => {
    expect(isRefreshableAuthError(new ApiError(403, 'GATE_PENDING', 'x'))).toBe(false)
    expect(isRefreshableAuthError(new ApiError(429, 'RATE_LIMITED', 'x'))).toBe(false)
  })
})
