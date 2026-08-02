import { apiFetch } from './client'
import type { EnumsResponse, RegisterRequest, RegisterResponse } from './types'

/**
 * Typed wrappers so screens never hand-write a path or a shape.
 *
 * NOTE ON SERVER USAGE: only unauthenticated calls may run on the server. The
 * access token lives in module state (tdd.md §3.10), which on the server is
 * shared across requests and would leak between users. `getEnums` is safe
 * because the endpoint takes no auth; everything else here is client-only.
 */

export function getEnums(signal?: AbortSignal): Promise<EnumsResponse> {
  return apiFetch<EnumsResponse>('/reference/enums', signal ? { signal } : {})
}

/**
 * Registration deliberately returns no session: the account starts at
 * `email_verification_pending` and a token is only issued once the address is
 * confirmed (tdd.md §3.1).
 */
export function register(body: RegisterRequest): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>('/auth/register', { method: 'POST', body })
}
