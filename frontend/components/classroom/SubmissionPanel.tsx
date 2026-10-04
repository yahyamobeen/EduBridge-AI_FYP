'use client'

import { useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { CheckCircleIcon } from '@/components/ui/Icon'
import { saveSubmission, turnInSubmission, unsubmitSubmission } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { AssignmentDetail, MySubmission } from '@/lib/api/types'
import { StatusChip } from './AssignmentParts'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * A student's own work on one assignment — three states, all decided by the
 * server's answer rather than tracked here:
 *
 *   editing    no `turned_in_at`: save a draft, turn in ("Mark as done" when empty)
 *   turned in  `turned_in_at` set: read-only, with Unsubmit
 *   returned   `returned_at` set: read-only, with the grade and private feedback
 *
 * Once the teacher saves ANY grade the server locks the work and answers
 * `details.reason = 'graded'` — even before the grade is returned, which is
 * why this can say "your teacher has started grading" without showing a grade.
 */
export function SubmissionPanel({
  assignment,
  onChange,
}: {
  assignment: AssignmentDetail & { my_submission: MySubmission }
  onChange: (s: MySubmission) => void
}) {
  const t = useTranslations('classroom.submission')
  const format = useFormatter()
  const sub = assignment.my_submission
  const [body, setBody] = useState(sub.body)
  const [link, setLink] = useState(sub.link_url ?? '')
  const [busy, setBusy] = useState<'save' | 'turnIn' | 'unsubmit' | null>(null)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = body !== sub.body || link.trim() !== (sub.link_url ?? '')
  const empty = body.trim() === '' && link.trim() === ''

  function explain(caught: unknown): string {
    if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
      if (caught.details.reason === 'graded') return t('locked')
      if (caught.details.reason === 'turned_in') return t('unsubmitFirst')
      if (caught.fieldErrors().link_url) return t('linkInvalid')
    }
    return t('failed')
  }

  async function act(kind: 'save' | 'turnIn' | 'unsubmit') {
    setBusy(kind)
    setError(null)
    setSaved(false)
    const draft = { body, link_url: link.trim() || null }
    try {
      let next: MySubmission
      if (kind === 'save') next = await saveSubmission(assignment.id, draft)
      else if (kind === 'unsubmit') next = await unsubmitSubmission(assignment.id)
      else {
        // Unsaved edits go in with the work, not lost behind it.
        if (dirty) await saveSubmission(assignment.id, draft)
        next = await turnInSubmission(assignment.id)
      }
      onChange(next)
      setBody(next.body)
      setLink(next.link_url ?? '')
      setSaved(kind === 'save')
    } catch (caught) {
      setError(explain(caught))
    } finally {
      setBusy(null)
    }
  }

  const when = (iso: string) =>
    format.dateTime(new Date(iso), { dateStyle: 'medium', timeStyle: 'short' })

  return (
    <section aria-labelledby="submission-heading" className={CARD}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 id="submission-heading" className={`${CARD_HEADING} mb-0`}>
          {t('heading')}
        </h2>
        <StatusChip status={sub.status} />
      </div>

      {sub.returned_at !== null && (
        <div className="mb-4 rounded border border-status-verified/40 p-4">
          <p className="text-body-md font-semibold text-on-surface">
            {sub.grade !== null && assignment.points !== null
              ? t('grade', { grade: format.number(sub.grade), points: assignment.points })
              : t('returned')}
          </p>
          {sub.feedback && (
            <>
              <h3 className="mt-3 text-label-caps uppercase text-on-surface-variant">
                {t('feedbackHeading')}
              </h3>
              <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">
                {sub.feedback}
              </p>
            </>
          )}
        </div>
      )}

      {sub.turned_in_at !== null || sub.returned_at !== null ? (
        <>
          {sub.turned_in_at !== null && (
            <p className="mb-3 text-body-sm text-on-surface-variant">
              {t('turnedInAt', { date: when(sub.turned_in_at) })}
            </p>
          )}
          {sub.body && (
            <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">
              {sub.body}
            </p>
          )}
          <SubmittedLink href={sub.link_url} />
          {sub.returned_at === null && (
            <>
              <p className="mt-4 text-body-sm text-on-surface-variant">{t('unsubmitHint')}</p>
              <button
                type="button"
                className={`${SECONDARY_BUTTON} mt-3`}
                disabled={busy !== null}
                onClick={() => void act('unsubmit')}
              >
                {t('unsubmit')}
              </button>
            </>
          )}
        </>
      ) : (
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            if (busy === null) void act('turnIn')
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor={`work-${assignment.id}`} className={LABEL}>
              {t('bodyLabel')}
            </label>
            <textarea
              id={`work-${assignment.id}`}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={20000}
              rows={6}
              className={FIELD}
            />
          </div>
          <div>
            <label htmlFor={`link-${assignment.id}`} className={LABEL}>
              {t('linkLabel')}
            </label>
            <input
              id={`link-${assignment.id}`}
              type="url"
              inputMode="url"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              maxLength={2048}
              placeholder="https://"
              aria-describedby={`link-hint-${assignment.id}`}
              className={`force-ltr ${FIELD}`}
            />
            <p
              id={`link-hint-${assignment.id}`}
              className="mt-1 text-body-sm text-on-surface-variant"
            >
              {t('linkHint')}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            {saved && !dirty && (
              <span
                role="status"
                className="flex items-center gap-1 text-body-sm text-status-verified"
              >
                <CheckCircleIcon className="h-4 w-4" />
                {t('saved')}
              </span>
            )}
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={busy !== null || !dirty}
              onClick={() => void act('save')}
            >
              {busy === 'save' ? t('saving') : t('save')}
            </button>
            <button type="submit" className={PRIMARY_BUTTON} disabled={busy !== null}>
              {busy === 'turnIn' ? t('turningIn') : empty ? t('markDone') : t('turnIn')}
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </section>
  )
}

/**
 * The server only ever stores an https:// link (ck_submission_link), so this
 * check should never fail — it is here so that a link is never rendered as an
 * anchor on the client's word alone.
 */
export function SubmittedLink({ href }: { href: string | null }) {
  if (!href) return null
  return href.startsWith('https://') ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="force-ltr mt-2 block break-all text-body-md text-primary underline"
    >
      {href}
    </a>
  ) : (
    <p className="force-ltr mt-2 break-all text-body-md text-on-surface">{href}</p>
  )
}
