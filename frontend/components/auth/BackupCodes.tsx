'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { KeyIcon } from '@/components/ui/Icon'

/**
 * The ten backup codes, shown exactly once (SEC-14).
 *
 * The safeguard against losing them is the ACKNOWLEDGEMENT CHECKBOX gating the
 * continue button — not a warning banner and not `beforeunload`, which mobile
 * Safari ignores and which a user swiping away never sees. A deliberate act is
 * the only thing that survives an unreliable unload event.
 *
 * Copy and download are both offered because neither works everywhere: the
 * clipboard API needs a secure context and a permission the browser may refuse,
 * and a download is awkward on a shared phone. If the clipboard is unavailable
 * the codes are still on screen and still selectable — the failure is visible
 * rather than silent.
 */
export function BackupCodes({
  codes,
  onContinue,
}: {
  codes: string[]
  onContinue: () => void
}) {
  const t = useTranslations('auth.backupCodes')
  const [acknowledged, setAcknowledged] = useState(false)
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')
  const [downloadFailed, setDownloadFailed] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied('done')
    } catch {
      setCopied('failed')
    }
  }

  /**
   * TWO BUGS LIVED IN THE FOUR LINES THIS REPLACES, and both produced NO file
   * and NO error — on codes that are shown exactly once and never shown again.
   *
   *  1. The anchor was never added to the document. A programmatic click on a
   *     detached anchor is not reliably honoured; Firefox is the failure case.
   *  2. `URL.revokeObjectURL` ran on the same tick as `click()`, destroying the
   *     blob before the download had started reading it.
   *
   * The `catch` matters as much as the fix. `copy()` directly above already
   * surfaces its failure, and the file's own docstring says the point is that
   * "the failure is visible rather than silent" — this function was the one
   * that did not follow it.
   */
  function download() {
    try {
      const blob = new Blob([`${t('fileHeading')}\n\n${codes.join('\n')}\n`], {
        type: 'text/plain',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'edubridge-backup-codes.txt'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      // Deferred, so the download has the object URL for as long as it needs
      // it. Revoking synchronously is what broke it.
      setTimeout(() => URL.revokeObjectURL(url), 0)
      setDownloadFailed(false)
    } catch {
      setDownloadFailed(true)
    }
  }

  return (
    <div className="flex flex-col space-y-6 motion-safe:animate-fade-in-up">
      <div className="flex flex-col items-center text-center">
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container">
          <KeyIcon className="h-8 w-8" />
        </div>
        <h1 className="mb-2 font-headline text-headline-md text-on-surface">{t('title')}</h1>
        <p className="text-body-md text-on-surface-variant">{t('body')}</p>
      </div>

      {/*
        force-ltr: these are Latin-alphanumeric strings and must not reorder
        inside an Urdu page (prd.md I18N-4).
      */}
      <ul className="force-ltr grid grid-cols-2 gap-2 rounded border border-outline-variant bg-surface p-4">
        {codes.map((code) => (
          <li
            key={code}
            className="select-all text-center font-mono text-body-md tracking-wider text-on-surface"
          >
            {code}
          </li>
        ))}
      </ul>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={copy}
          className="flex-1 rounded border border-outline-variant px-4 py-3 text-body-sm font-semibold text-on-surface transition-colors hover:bg-surface-container-low"
        >
          {copied === 'done' ? t('copied') : t('copy')}
        </button>
        <button
          type="button"
          onClick={download}
          className="flex-1 rounded border border-outline-variant px-4 py-3 text-body-sm font-semibold text-on-surface transition-colors hover:bg-surface-container-low"
        >
          {t('download')}
        </button>
      </div>

      {copied === 'failed' && (
        <p role="status" className="text-body-sm text-on-surface-variant">
          {t('copyFailed')}
        </p>
      )}

      {downloadFailed && (
        <p role="status" className="text-body-sm text-on-surface-variant">
          {t('downloadFailed')}
        </p>
      )}

      <label className="flex cursor-pointer items-start gap-3 rounded border border-outline-variant bg-surface-container-low p-4">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 rounded-sm border-outline-variant text-primary focus:ring-primary"
        />
        <span className="text-body-sm text-on-surface">{t('acknowledge')}</span>
      </label>

      <button
        type="button"
        onClick={onContinue}
        disabled={!acknowledged}
        className="w-full rounded bg-primary-container px-4 py-4 text-label-caps uppercase tracking-wider text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t('continue')}
      </button>
    </div>
  )
}
