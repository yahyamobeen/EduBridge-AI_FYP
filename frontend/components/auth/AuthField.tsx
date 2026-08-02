'use client'

import { useId, useState, type ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { ErrorText } from '@/components/ui/FormFeedback'
import { EyeIcon, EyeOffIcon } from '@/components/ui/Icon'

/**
 * The login prototype's field: a leading glyph inside the control, a caps label
 * with an optional trailing link on the same row, and — for passwords — an eye
 * toggle at the far end.
 *
 * Kept separate from the signup `TextField` rather than bolted onto it: the two
 * prototypes genuinely differ (label row with a link, inset icons, an 8px label
 * gap instead of 6px), and widening one component to render both shapes would
 * make each screen harder to match to its source.
 *
 * Measured from the prototype: 12px padding block, 40px inline start inset for
 * the glyph, 8px radius, `surface-sandbox` fill, `outline-variant` border.
 */
export function AuthField({
  label,
  name,
  type = 'text',
  icon,
  autoComplete,
  placeholder,
  value,
  onChange,
  error,
  labelAction,
  required,
  disabled,
}: {
  label: string
  name: string
  type?: 'text' | 'email' | 'password'
  icon: ReactNode
  autoComplete?: string
  placeholder?: string
  value: string
  onChange: (next: string) => void
  error?: string | undefined
  /** Rendered at the end of the label row — the prototype's "Forgot Password?". */
  labelAction?: ReactNode
  required?: boolean
  disabled?: boolean
}) {
  const id = useId()
  const errorId = `${id}-error`
  const t = useTranslations('signup.common')
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor={id} className="block text-label-caps uppercase text-on-surface-variant">
          {label}
        </label>
        {labelAction}
      </div>

      <div className="relative">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-outline"
        >
          {icon}
        </span>

        <input
          id={id}
          name={name}
          type={isPassword && revealed ? 'text' : type}
          // Password managers cannot fill a field they cannot identify, and the
          // target audience shares devices (prd.md §3.1).
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          disabled={disabled}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? errorId : undefined}
          className={`block w-full rounded border bg-surface-sandbox py-3 ps-10 text-body-md text-on-surface transition-shadow focus:ring-2 focus:ring-primary disabled:opacity-60 ${
            isPassword ? 'pe-10' : 'pe-3'
          } ${error ? 'border-error' : 'border-outline-variant focus:border-primary'}`}
        />

        {isPassword && (
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            aria-label={revealed ? t('hidePassword') : t('showPassword')}
            className="absolute inset-y-0 end-0 flex items-center pe-3 text-outline transition-colors hover:text-on-surface"
          >
            {revealed ? <EyeOffIcon className="h-5 w-5" /> : <EyeIcon className="h-5 w-5" />}
          </button>
        )}
      </div>

      {error && <ErrorText id={errorId}>{error}</ErrorText>}
    </div>
  )
}
