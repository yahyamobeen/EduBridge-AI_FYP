import type { MeResponse } from '@/lib/api/types'

/**
 * `MeResponse.full_name` is nullable, and every screen that shows a name has to
 * decide what to do about that.
 *
 * ⚠️ IT USED TO BE TYPED `string`, so nobody decided. The four dashboards each
 * wrote `me.full_name.split(' ')[0] ?? me.full_name`, and that `??` is easy to
 * misread twice over. It is NOT dead code — `noUncheckedIndexedAccess` is on,
 * so `split(...)[0]` is `string | undefined` and the fallback is what satisfies
 * the compiler. But it is also NOT a null guard: it only ever fired for an
 * index that cannot be missing, while the real hazard — a null name throwing on
 * `.split` — was invisible, because the client type said the field could not be
 * null. `app_user.full_name` IS nullable (initial_schema.sql:103) and the API
 * says so (`schemas.py:225`); `Guardian.test.tsx:188` records the 500 that the
 * same mistake caused on the guardian-confirm path.
 *
 * The fallback chain ends at the local part of the email address rather than at
 * an empty string, so a nameless account still renders something a human
 * recognises. Nothing here throws: a missing name must never be the reason a
 * dashboard fails to render.
 */

/** Local part of the address — the last resort when there is no name at all. */
function emailHandle(email: string): string {
  return email.split('@')[0] ?? email
}

/** First word of the name, for "Welcome back, {name}". */
export function firstName(me: Pick<MeResponse, 'full_name' | 'email'>): string {
  const full = me.full_name?.trim()
  if (!full) return emailHandle(me.email)
  return full.split(/\s+/)[0] ?? full
}

/** Whole name where there is room for it. Never an empty string. */
export function displayName(me: Pick<MeResponse, 'full_name' | 'email'>): string {
  return me.full_name?.trim() || emailHandle(me.email)
}

/** Single letter for an avatar. `?` when even the address cannot supply one. */
export function avatarInitial(me: Pick<MeResponse, 'full_name' | 'email'>): string {
  return displayName(me).trim().charAt(0).toUpperCase() || '?'
}
