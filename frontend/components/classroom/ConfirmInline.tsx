'use client'

import { useTranslations } from 'next-intl'
import { DANGER_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * A second, explicit step before a destructive action — removing a student,
 * leaving a class, archiving, turning joining off.
 *
 * Inline rather than a modal dialog: jsdom (the test environment) implements no
 * `HTMLDialogElement.showModal`, so a native `<dialog>` could not be tested, and
 * an inline panel keeps focus and reading order exactly where the user already
 * is. `role="alertdialog"` with the question as its label tells assistive
 * technology this needs an answer.
 */
export function ConfirmInline({
  question,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  question: string
  confirmLabel: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const t = useTranslations('classroom.confirm')
  return (
    <div
      role="alertdialog"
      aria-label={question}
      className="mt-3 rounded border border-error/40 bg-error-container/40 p-4"
    >
      <p className="mb-3 text-body-md text-on-surface">{question}</p>
      <div className="flex flex-wrap gap-3">
        <button type="button" className={DANGER_BUTTON} disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" className={SECONDARY_BUTTON} disabled={busy} onClick={onCancel}>
          {t('cancel')}
        </button>
      </div>
    </div>
  )
}
