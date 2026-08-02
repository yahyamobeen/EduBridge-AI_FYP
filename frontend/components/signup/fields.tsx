'use client'

import { useId, useState } from 'react'
import { useTranslations } from 'next-intl'
import { CheckIcon } from '@/components/ui/Icon'

/**
 * Form primitives shared by the three signup flows.
 *
 * Two accessibility rules from prd.md A11Y-1 are baked in here rather than
 * left to each caller: the label is always visible (never placeholder-only),
 * and an error is conveyed by icon, text and colour together — never colour
 * alone — and wired to the input through aria-describedby.
 */

type FieldProps = {
  label: string
  name: string
  type?: 'text' | 'email' | 'password'
  autoComplete?: string
  placeholder?: string
  hint?: string
  error?: string | undefined
  required?: boolean
  defaultValue?: string
  register?: Record<string, unknown>
}

function ErrorText({ id, children }: { id: string; children: string }) {
  return (
    <p
      id={id}
      role="alert"
      className="mt-1.5 flex items-center gap-1.5 text-body-sm text-error"
    >
      <svg
        viewBox="0 0 20 20"
        className="h-4 w-4 shrink-0"
        aria-hidden="true"
        fill="currentColor"
      >
        <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4a1 1 0 0 1 1 1v4a1 1 0 1 1-2 0V7a1 1 0 0 1 1-1zm0 9.5a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5z" />
      </svg>
      {children}
    </p>
  )
}

export function TextField({
  label,
  name,
  type = 'text',
  autoComplete,
  placeholder,
  hint,
  error,
  required,
  register,
}: FieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const t = useTranslations('signup.common')
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'
  const inputType = isPassword && revealed ? 'text' : type

  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-label-caps uppercase text-on-surface-variant"
      >
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          name={name}
          type={inputType}
          // Password managers cannot fill a field they cannot identify, and
          // the target audience shares devices (prd.md §3.1).
          autoComplete={autoComplete}
          placeholder={placeholder}
          required={required}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={[error ? errorId : null, hint ? hintId : null]
            .filter(Boolean)
            .join(' ')}
          className={`w-full rounded border bg-surface px-4 py-3 text-body-md text-on-surface transition-shadow focus:ring-2 focus:ring-primary ${
            isPassword ? 'pe-12' : ''
          } ${error ? 'border-error' : 'border-outline-variant focus:border-primary'}`}
          {...register}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            className="absolute end-3 top-1/2 -translate-y-1/2 text-body-sm font-semibold text-on-surface-variant hover:text-primary"
          >
            {revealed ? t('hidePassword') : t('showPassword')}
          </button>
        )}
      </div>
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-body-sm text-outline">
          {hint}
        </p>
      )}
      {error && <ErrorText id={errorId}>{error}</ErrorText>}
    </div>
  )
}

export type Option = { value: string; label: string; sublabel?: string }

/**
 * Radio cards, as in the prototype.
 *
 * Selection styling uses `peer-checked:`, NOT `:has()`. The prototypes carry
 * both, but `:has()` silently does nothing on older Android WebView — and a
 * board or class that shows no selected state makes the form unusable on
 * exactly the devices prd.md §3.1 targets.
 */
export function RadioCards({
  legend,
  name,
  options,
  value,
  onChange,
  columns = 2,
  compact = false,
  error,
  hint,
  disabledMessage,
}: {
  legend: string
  name: string
  options: Option[]
  value: string
  onChange: (next: string) => void
  columns?: 2 | 3 | 4
  compact?: boolean
  error?: string | undefined
  hint?: string
  disabledMessage?: string
}) {
  const errorId = useId()
  const cols = {
    2: 'grid-cols-2',
    3: 'grid-cols-1 sm:grid-cols-3',
    4: 'grid-cols-2 sm:grid-cols-4',
  }

  return (
    <fieldset>
      <legend className="mb-3 block text-label-caps uppercase text-on-surface-variant">
        {legend}
      </legend>

      {options.length === 0 ? (
        <p className="rounded border border-dashed border-outline-variant px-4 py-3 text-body-sm text-on-surface-variant">
          {disabledMessage}
        </p>
      ) : (
        <div
          className={`grid gap-3 ${cols[columns]}`}
          aria-describedby={error ? errorId : undefined}
        >
          {options.map((option) => (
            <label
              key={option.value}
              className={`relative flex cursor-pointer rounded border bg-surface transition-colors hover:border-primary ${
                compact ? 'items-center justify-center py-3 text-center' : 'p-4'
              } ${value === option.value ? 'border-primary bg-student-blue' : 'border-outline-variant'}`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={value === option.value}
                onChange={() => onChange(option.value)}
                className="peer sr-only"
              />
              <span className="flex w-full flex-col gap-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="font-headline text-body-md font-semibold text-on-surface peer-checked:text-primary">
                    {option.label}
                  </span>
                  {!compact && value === option.value && (
                    <CheckIcon className="h-4 w-4 shrink-0 text-primary" />
                  )}
                </span>
                {option.sublabel && (
                  <span className="text-body-sm text-on-surface-variant">
                    {option.sublabel}
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
      )}

      {hint && !error && <p className="mt-2 text-body-sm text-outline">{hint}</p>}
      {error && <ErrorText id={errorId}>{error}</ErrorText>}
    </fieldset>
  )
}

/** Form-level failure: rate limiting, an invalid pair, an unknown code. */
export function FormBanner({ children }: { children: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded border border-error/40 bg-error-container px-4 py-3 text-body-sm text-on-error-container"
    >
      <svg
        viewBox="0 0 20 20"
        className="mt-0.5 h-4 w-4 shrink-0"
        aria-hidden
        fill="currentColor"
      >
        <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4a1 1 0 0 1 1 1v4a1 1 0 1 1-2 0V7a1 1 0 0 1 1-1zm0 9.5a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5z" />
      </svg>
      {children}
    </div>
  )
}
