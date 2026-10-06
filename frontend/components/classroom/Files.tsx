'use client'

import { useId, useRef, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ApiError } from '@/lib/api/errors'
import type { FileMeta, FileRefusalReason, ViewLink } from '@/lib/api/types'
import { openInNewTab, saveBlob } from '@/lib/download'
import { ACCEPT, earlyRefusal, isViewable } from '@/lib/files'
import { ConfirmInline } from './ConfirmInline'
import { LABEL, SECONDARY_BUTTON } from './styles'

/**
 * A list of files with download, view and — when the caller passes `upload` /
 * `remove` — adding and removing (classroom Phase 6, prd.md CL-8). Used for a
 * teacher's attachments on a post or an assignment; a student's own work uses
 * `WorkAttachments`, which shares `FileItem`.
 *
 * The SERVER is the check: it reads the type from the bytes and enforces every
 * limit (lib/files.ts only spares a doomed upload). A download is always saved,
 * never opened inside the application; since Phase 6b a PDF or an image can
 * also be VIEWED, in a new tab on the storage service's own domain.
 */

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

/** A `classroom.files` key for a refusal, chosen by `details.reason`, never `message`. */
export function fileErrorKey(caught: unknown, fallback: string): string {
  const reason =
    caught instanceof ApiError && caught.code === 'VALIDATION_ERROR'
      ? (caught.details.reason as FileRefusalReason | undefined)
      : undefined
  return (reason && REASON_KEY[reason]) || fallback
}

/** "240 KB" / "2.4 MB", in the reader's own number format. */
export function useSizeLabel(): (bytes: number) => string {
  const t = useTranslations('classroom.files')
  const format = useFormatter()
  return (bytes) =>
    bytes < 1024 * 1024
      ? t('sizeKb', { size: format.number(Math.max(1, Math.round(bytes / 1024))) })
      : t('sizeMb', {
          size: format.number(bytes / (1024 * 1024), { maximumFractionDigits: 1 }),
        })
}

/** Download, view and (optionally) remove one file; the list around it is the caller's. */
export function FileItem({
  file,
  busy,
  download,
  view,
  remove,
  onError,
}: {
  file: FileMeta
  busy: boolean
  download: (file: FileMeta) => Promise<Blob>
  view?: (file: FileMeta) => Promise<ViewLink>
  /** Resolves once the file is gone; the caller drops it from its list. */
  remove?: (file: FileMeta) => Promise<void>
  onError: (message: string | null) => void
}) {
  const t = useTranslations('classroom.files')
  const sizeLabel = useSizeLabel()
  const [confirming, setConfirming] = useState(false)
  const [removing, setRemoving] = useState(false)

  async function save() {
    onError(null)
    try {
      saveBlob(await download(file), file.filename)
    } catch {
      onError(t('downloadFailed'))
    }
  }

  function show() {
    onError(null)
    // Not awaited before the tab opens: openInNewTab must run inside the click.
    openInNewTab(async () => (await view!(file)).url).catch(() => onError(t('viewFailed')))
  }

  async function drop() {
    setRemoving(true)
    onError(null)
    try {
      await remove!(file)
    } catch (caught) {
      onError(t(fileErrorKey(caught, 'removeFailed')))
      setRemoving(false)
    }
  }

  return (
    <li className="px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => void save()}
          aria-label={t('download', { name: file.filename })}
          className="min-w-0 text-start text-body-md text-primary underline"
        >
          <span className="break-all">{file.filename}</span>
        </button>
        <span className="flex items-center gap-3 text-body-sm text-on-surface-variant">
          {sizeLabel(file.size_bytes)}
          {view && isViewable(file.content_type) && (
            <button
              type="button"
              onClick={show}
              aria-label={t('viewLabel', { name: file.filename })}
              className="text-primary underline"
            >
              {t('view')}
            </button>
          )}
          {remove && !confirming && (
            <button
              type="button"
              disabled={busy || removing}
              onClick={() => setConfirming(true)}
              aria-label={t('removeLabel', { name: file.filename })}
              className="text-error underline disabled:opacity-50"
            >
              {t('remove')}
            </button>
          )}
        </span>
      </div>
      {remove && confirming && (
        <ConfirmInline
          question={t('removeConfirm', { name: file.filename })}
          confirmLabel={t('remove')}
          busy={removing}
          onConfirm={() => void drop()}
          onCancel={() => setConfirming(false)}
        />
      )}
    </li>
  )
}

export function FileSection({
  heading,
  files,
  download,
  view,
  upload,
  remove,
  onChange,
}: {
  heading: string
  files: FileMeta[]
  download: (file: FileMeta) => Promise<Blob>
  view?: (file: FileMeta) => Promise<ViewLink>
  upload?: (file: File) => Promise<FileMeta>
  remove?: (file: FileMeta) => Promise<void>
  onChange?: (files: FileMeta[]) => void
}) {
  const t = useTranslations('classroom.files')
  const input = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (files.length === 0 && !upload) return null

  async function add(file: File) {
    setError(null)
    const early = earlyRefusal(file)
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
      setError(t(fileErrorKey(caught, 'uploadFailed')))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="mt-4">
      <p className={LABEL}>{heading}</p>
      {files.length > 0 && (
        <ul className="divide-y divide-outline-variant rounded border border-outline-variant">
          {files.map((f) => (
            <FileItem
              key={f.id}
              file={f}
              busy={busy}
              download={download}
              view={view}
              remove={
                remove &&
                (async (gone) => {
                  await remove(gone)
                  onChange?.(files.filter((x) => x.id !== gone.id))
                })
              }
              onError={setError}
            />
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
