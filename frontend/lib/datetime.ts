/**
 * `<input type="datetime-local">` speaks the user's wall-clock time with no
 * offset ("2026-10-05T14:30"); the API speaks ISO instants WITH an offset, and
 * refuses a naive one (the backend's AwareDatetime). These two functions are
 * the only bridge between them.
 *
 * ECMAScript parses a date-time string with no offset as LOCAL time, so
 * `new Date(value)` is the right instant — the conversion the backend refuses
 * to guess is made here, where the user's zone is actually known.
 */

const pad = (n: number) => String(n).padStart(2, '0')

export function localInputToIso(value: string): string {
  return new Date(value).toISOString()
}

export function isoToLocalInput(iso: string): string {
  return toLocalInput(new Date(iso))
}

/** Now, rounded down to the minute — the `min` of a schedule input. */
export function nowLocalInput(): string {
  return toLocalInput(new Date())
}

function toLocalInput(d: Date): string {
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  )
}
