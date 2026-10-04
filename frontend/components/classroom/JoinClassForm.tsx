'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { useRouter } from '@/i18n/navigation'
import { joinSpace } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { JoinFailureReason, JoinMismatchSpace } from '@/lib/api/types'
import { CARD, CARD_HEADING, FIELD, LABEL, PRIMARY_BUTTON } from './styles'

/**
 * Join a class by its code — POST /spaces/join.
 *
 * The code is normalised for DISPLAY and for the enable rule only; the server
 * normalises again and is the authority. Every refusal arrives as a catalogued
 * code with a `details.reason`, and this branches on that — never on the
 * message (frontend/CLAUDE.md §3). A removed student deliberately receives the
 * same `invalid_code` as a mistyped one, so nothing here can tell them apart.
 */
export function JoinClassForm() {
  const t = useTranslations('classroom.join')
  const router = useRouter()
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const normalised = code.toUpperCase().replace(/[^A-Z0-9]/g, '')
  const canSubmit = normalised.length === 8 && !submitting

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const { space_id } = await joinSpace(normalised)
      router.push(`/classroom/${space_id}`)
    } catch (caught) {
      // Navigates away on success, so the button is re-enabled only on failure.
      setSubmitting(false)
      setError(messageFor(caught))
    }
  }

  function messageFor(caught: unknown): string {
    if (!(caught instanceof ApiError)) return t('failed')
    if (caught.code === 'GATE_PENDING') return t('gatePending')
    if (caught.code === 'RATE_LIMITED') return t('rateLimited')
    if (caught.code !== 'VALIDATION_ERROR') return t('failed')
    const reason = caught.details.reason as JoinFailureReason | undefined
    if (reason === 'class_mismatch') {
      const space = caught.details.space as JoinMismatchSpace | undefined
      return space
        ? t('mismatch', { classLevel: space.class_level, board: space.board })
        : t('invalid')
    }
    if (reason === 'classroom_full') return t('full')
    return t('invalid')
  }

  return (
    <form onSubmit={submit} noValidate className={CARD}>
      <h2 className={CARD_HEADING}>{t('heading')}</h2>
      <label htmlFor="join-code" className={LABEL}>
        {t('label')}
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          id="join-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={16}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-describedby="join-code-hint"
          className={`force-ltr ${FIELD} font-mono tracking-widest`}
        />
        <button type="submit" disabled={!canSubmit} className={PRIMARY_BUTTON}>
          {submitting ? t('joining') : t('submit')}
        </button>
      </div>
      <p id="join-code-hint" className="mt-1.5 text-body-sm text-outline">
        {t('hint')}
      </p>
      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </form>
  )
}
