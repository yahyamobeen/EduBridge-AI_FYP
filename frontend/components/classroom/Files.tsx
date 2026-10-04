'use client'

import { useId, useRef, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ApiError } from '@/lib/api/errors'
import type { FileMeta, FileRefusalReason } from '@/lib/api/types'
import { saveBlob } from '@/lib/download'
import { ConfirmInline } from './ConfirmInline'
import { LABEL, SECONDARY_BUTTON } from './styles'

/**
 * A list of files with download, and — when the caller passes `upload` /
 * `remove` — adding and removing (classroom Phase 6, prd.md CL-8). Used for a
 * teacher's attachments on a post or an assignment, a student's own files on
 * their work, and the teacher's read-only view of that work.
 *
 * The SERVER is the check: it reads the type from the bytes and enforces every
 * limit. The two checks here (size, extension) only save a student waiting on
 * an upload that is certain to be refused. A file is always downloaded, never
 * opened inside the application.
 */

const MAX_BYTES = 5 * 1024 * 1024
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.docx,.pptx'
const EXTENSIONS = new Set(['pdf', 'png', 'jpg', 'jpeg', 'docx', 'pptx'])

const REASON_KEY: Partial<Record<FileRefusalReason, string>> = {
  unsupported_type: 'unsupportedType',
  too_large: 'tooLarge',
  empty: 'empty',
  too_many_files: 'tooManyFiles',
  submission_quota: 'submissionQuota',
  classroom_quota: 'classroomQuota',
  graded: 'locked',
  turned_in: 'turnedIn',
}

export function FileSection({
  heading,
  files,
  download,
  upload,
  remove,
  onChange,
}: {
  heading: string
  files: FileMeta[]
  download: (file: FileMeta) => Promise<Blob>
  upload?: (file: File) => Promise<FileMeta>
  remove?: (file: FileMeta) => Promise<void>
  onChange?: (files: FileMeta[]) => void
}) {
  const t = useTranslations('classroom.files')
  const format = useFormatter()
  const input = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (files.length === 0 && !upload) return null

  const size = (bytes: number) =>
    bytes < 1024 * 1024
      ? t('sizeKb', { size: format.number(Math.max(1, Math.round(bytes / 1024))) })
      : t('sizeMb', {
          size: format.number(bytes / (1024 * 1024), { maximumFractionDigits: 1 }),
        })

  function explain(caught: unknown, fallback: string): string {
    const reason =
      caught instanceof ApiError && caught.code === 'VALIDATION_ERROR'
        ? (caught.details.reason as FileRefusalReason | undefined)
        : undefined
    const key = reason ? REASON_KEY[reason] : undefined
    return key ? t(key) : t(fallback)
  }

  async function add(file: File) {
    setError(null)
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    const early = !EXTENSIONS.has(extension)
      ? 'unsupportedType'
      : file.size > MAX_BYTES
        ? 'tooLarge'
        : file.size === 0
          ? 'empty'
          : null
    if (early) {
      setError(t(early))
      if (input.current) input.current.value = ''
      return
    }
    setBusy(true)
    try {
      const stored = await upload!(file)
      onChange?.([...files, stored])
    } catch (caught) {
      setError(explain(caught, 'uploadFailed'))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  async function drop(file: FileMeta) {
    setBusy(true)
    setError(null)
    try {
      await remove!(file)
      setConfirming(null)
      onChange?.(files.filter((f) => f.id !== file.id))
    } catch (caught) {
      setError(explain(caught, 'removeFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function save(file: FileMeta) {
    setError(null)
    try {
      saveBlob(await download(file), file.filename)
    } catch {
      setError(t('downloadFailed'))
    }
  }

  return (
    <div className="mt-4">
      <p className={LABEL}>{heading}</p>
      {files.length > 0 && (
        <ul className="divide-y divide-outline-variant rounded border border-outline-variant">
          {files.map((f) => (
            <li key={f.id} className="px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => void save(f)}
                  aria-label={t('download', { name: f.filename })}
                  className="min-w-0 text-start text-body-md text-primary underline"
                >
                  <span className="break-all">{f.filename}</span>
                </button>
                <span className="flex items-center gap-3 text-body-sm text-on-surface-variant">
                  {size(f.size_bytes)}
                  {remove && confirming !== f.id && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setConfirming(f.id)}
                      aria-label={t('removeLabel', { name: f.filename })}
                      className="text-error underline disabled:opacity-50"
                    >
                      {t('remove')}
                    </button>
                  )}
                </span>
              </div>
              {remove && confirming === f.id && (
                <ConfirmInline
                  question={t('removeConfirm', { name: f.filename })}
                  confirmLabel={t('remove')}
                  busy={busy}
                  onConfirm={() => void drop(f)}
                  onCancel={() => setConfirming(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {upload && (
        <div className="mt-2">
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            id={inputId}
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void add(file)
            }}
          />
          <label
            htmlFor={inputId}
            className={`${SECONDARY_BUTTON} inline-block cursor-pointer ${busy ? 'opacity-50' : ''}`}
          >
            {busy ? t('uploading') : t('add')}
          </label>
          <p className="mt-1 text-body-sm text-on-surface-variant">{t('hint')}</p>
        </div>
      )}
      {error && (
        <div className="mt-2">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </div>
  )
}
