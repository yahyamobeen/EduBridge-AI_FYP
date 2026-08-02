/**
 * Error presentation shared by every form in the app.
 *
 * prd.md A11Y-1 requires an error to be conveyed by icon, text AND colour --
 * never colour alone -- and to be wired to its control so assistive technology
 * announces it. Both rules live here rather than in each caller, so a new form
 * cannot quietly omit them.
 */

function AlertGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" fill="currentColor">
      <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4a1 1 0 0 1 1 1v4a1 1 0 1 1-2 0V7a1 1 0 0 1 1-1zm0 9.5a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5z" />
    </svg>
  )
}

/** Field-level error. `id` must be referenced by the control's aria-describedby. */
export function ErrorText({ id, children }: { id: string; children: string }) {
  return (
    <p
      id={id}
      role="alert"
      className="mt-1.5 flex items-center gap-1.5 text-body-sm text-error"
    >
      <AlertGlyph className="h-4 w-4 shrink-0" />
      {children}
    </p>
  )
}

/** Form-level failure: rate limiting, an invalid pair, an unknown code. */
export function FormBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded border border-error/40 bg-error-container px-4 py-3 text-body-sm text-on-error-container"
    >
      <AlertGlyph className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  )
}
