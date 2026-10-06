/**
 * Class strings shared by the classroom screens — the same tokens `Settings.tsx`
 * uses for its cards and buttons, kept in one place so four classroom files do
 * not each carry a copy. Logical properties only (lib/i18n-rules.test.ts).
 */

export const CARD =
  'rounded-xl border border-outline-variant bg-surface-container-lowest p-6 shadow-sm'

export const CARD_HEADING =
  'mb-4 flex items-center gap-2 font-headline text-headline-md text-primary'

export const LABEL = 'mb-1.5 block text-label-caps uppercase text-on-surface-variant'

export const FIELD =
  'w-full rounded border border-outline-variant bg-surface px-4 py-3 text-body-md text-on-surface transition-shadow focus:ring-2 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60'

export const PRIMARY_BUTTON =
  'rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50'

export const SECONDARY_BUTTON =
  'rounded border border-outline px-6 py-3 text-label-caps uppercase text-on-surface transition-colors hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-50'

export const DANGER_BUTTON =
  'rounded border border-error px-6 py-3 text-label-caps uppercase text-error transition-colors hover:bg-error-container disabled:cursor-not-allowed disabled:opacity-50'

/** UUID v4-shaped ids only; anything else is refused before a request is made. */
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
