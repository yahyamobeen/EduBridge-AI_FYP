'use client'

import { useEffect, useRef } from 'react'

/**
 * The large centred code field from the 2fa-challenge prototype.
 *
 * Measured from the prototype rather than copied by class name: 66px tall,
 * 16px/12px padding, 8px radius, JetBrains Mono at 24px/32px weight 600 with
 * 0.5em tracking, on the `surface` fill with an `outline-variant` border.
 *
 * TWO DELIBERATE DEPARTURES, both correctness rather than taste:
 *
 *  1. `type="text"` with `inputMode="numeric"`, not the prototype's
 *     `type="number"`. A number input drops a leading zero in several engines,
 *     shows spinners, and ignores `maxlength` entirely -- which is why the
 *     prototype needed an `oninput` handler to re-slice the value. A one-time
 *     code is a string of digits, not a quantity.
 *
 *  2. `autocomplete="one-time-code"` so Android and iOS offer the SMS/email
 *     code from the notification shade. A backup code is not a one-time code
 *     from the browser's point of view, so it opts out instead of mislabelling
 *     itself to the password manager.
 */
export function CodeInput({
  id,
  label,
  value,
  onChange,
  onEnter,
  length,
  alphanumeric = false,
  invalid = false,
  describedBy,
  focusKey = 0,
  disabled = false,
}: {
  id: string
  label: string
  value: string
  onChange: (next: string) => void
  onEnter?: () => void
  length: number
  alphanumeric?: boolean
  invalid?: boolean
  describedBy?: string | undefined
  /**
   * Focus is taken whenever this value changes. Switching method and clearing a
   * rejected code both have to return the cursor here, or a keyboard or
   * screen-reader user is stranded on the control they just left.
   */
  focusKey?: number
  disabled?: boolean
}) {
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    ref.current?.focus()
  }, [focusKey])

  function handle(raw: string) {
    const cleaned = alphanumeric
      ? raw.toUpperCase().replace(/[^0-9A-Z]/g, '')
      : raw.replace(/\D/g, '')
    onChange(cleaned.slice(0, length))
  }

  return (
    <div className="flex flex-col">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        name={id}
        type="text"
        inputMode={alphanumeric ? 'text' : 'numeric'}
        autoComplete={alphanumeric ? 'off' : 'one-time-code'}
        autoCorrect="off"
        spellCheck={false}
        maxLength={length}
        disabled={disabled}
        value={value}
        onChange={(event) => handle(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && onEnter) {
            event.preventDefault()
            onEnter()
          }
        }}
        placeholder={'0'.repeat(length)}
        aria-invalid={invalid ? 'true' : undefined}
        aria-describedby={describedBy}
        /* force-ltr: digits must not reorder inside an Urdu page. */
        className={`force-ltr w-full rounded border bg-surface px-3 py-4 text-center font-mono text-headline-md tracking-[0.5em] text-on-surface transition-colors placeholder:text-outline-variant/50 focus:outline-none focus:ring-4 focus:ring-primary-container/10 disabled:opacity-60 ${
          invalid
            ? 'border-error text-error'
            : 'border-outline-variant focus:border-primary-container'
        }`}
      />
    </div>
  )
}
