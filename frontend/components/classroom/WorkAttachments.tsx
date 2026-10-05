'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import {
  addSubmissionLink,
  deleteSubmissionFile,
  deleteSubmissionLink,
  downloadSubmissionFile,
  uploadSubmissionFile,
  viewSubmissionFile,
} from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { FileMeta, LinkMeta, LinkRefusalReason } from '@/lib/api/types'
import { ACCEPT, earlyRefusal } from '@/lib/files'
import { ConfirmInline } from './ConfirmInline'
import { FileItem, fileErrorKey } from './Files'
import { FIELD, LABEL, SECONDARY_BUTTON } from './styles'

/**
 * Everything attached to one student's work — files and links in one list, in
 * the order they were added, with a single "+ Add" menu (File / Link), like
 * Google Classroom (classroom Phase 6b, owner request 2026-10-05).
 *
 * Who sees it is the database's decision, not this component's: the student
 * always, the teacher once the work is turned in, a classmate never
 * (subfile_* and link_* policies). `edit` is passed only for the student's own
 * draft; the teacher's review and turned-in work are read-only.
 */

const LINK_REASON_KEY: Record<LinkRefusalReason, string> = {
  too_many_links: 'tooManyLinks',
  graded: 'locked',
  turned_in: 'turnedIn',
}

/** The server stores https only; checked here so a link is never rendered on trust. */
function isHttpsLink(value: string): boolean {
  if (/\s/.test(value)) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname !== ''
  } catch {
    return false
  }
}

function LinkItem({
  link,
  remove,
  onError,
}: {
  link: LinkMeta
  remove?: (link: LinkMeta) => Promise<void>
  onError: (message: string | null) => void
}) {
  const t = useTranslations('classroom.files')
  const [confirming, setConfirming] = useState(false)
  const [removing, setRemoving] = useState(false)

  async function drop() {
    setRemoving(true)
    onError(null)
    try {
      await remove!(link)
    } catch (caught) {
      const reason =
        caught instanceof ApiError ? (caught.details.reason as LinkRefusalReason) : undefined
      onError(t((reason && LINK_REASON_KEY[reason]) || 'linkRemoveFailed'))
      setRemoving(false)
    }
  }

  return (
    <li className="px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {isHttpsLink(link.url) ? (
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="force-ltr min-w-0 break-all text-body-md text-primary underline"
          >
            {link.url}
          </a>
        ) : (
          <span className="force-ltr min-w-0 break-all text-body-md text-on-surface">
            {link.url}
          </span>
        )}
        {remove && !confirming && (
          <button
            type="button"
            disabled={removing}
            onClick={() => setConfirming(true)}
            aria-label={t('removeLinkLabel', { url: link.url })}
            className="text-body-sm text-error underline disabled:opacity-50"
          >
            {t('remove')}
          </button>
        )}
      </div>
      {remove && confirming && (
        <ConfirmInline
          question={t('removeLinkConfirm')}
          confirmLabel={t('remove')}
          busy={removing}
          onConfirm={() => void drop()}
          onCancel={() => setConfirming(false)}
        />
      )}
    </li>
  )
}

function menuItems(menu: HTMLElement | null): HTMLElement[] {
  return Array.from(menu?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])
}

/**
 * A menu button (WAI-ARIA): Enter, Space or ArrowDown opens it on the first
 * item; arrows, Home and End move; Escape closes it and returns focus; Tab or a
 * click elsewhere closes it.
 */
function AddMenu({
  disabled,
  onFile,
  onLink,
}: {
  disabled: boolean
  onFile: () => void
  onLink: () => void
}) {
  const t = useTranslations('classroom.files')
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    menuItems(menu.current)[0]?.focus()
    function outside(event: MouseEvent) {
      const target = event.target as Node
      if (!menu.current?.contains(target) && !button.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [open])

  function close(refocus: boolean) {
    setOpen(false)
    if (refocus) button.current?.focus()
  }

  function onMenuKey(event: React.KeyboardEvent) {
    const list = menuItems(menu.current)
    const at = list.indexOf(document.activeElement as HTMLElement)
    const move = (to: number) => {
      event.preventDefault()
      list[(to + list.length) % list.length]?.focus()
    }
    if (event.key === 'ArrowDown') move(at + 1)
    else if (event.key === 'ArrowUp') move(at - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(list.length - 1)
    else if (event.key === 'Escape') {
      event.preventDefault()
      close(true)
    } else if (event.key === 'Tab') close(false)
  }

  function choose(action: () => void) {
    close(false)
    action()
  }

  return (
    <div className="relative inline-block">
      <button
        ref={button}
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault()
            setOpen(true)
          }
        }}
        className={SECONDARY_BUTTON}
      >
        <span aria-hidden="true">+ </span>
        {t('addMenu')}
      </button>
      {open && (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={t('addMenu')}
          onKeyDown={onMenuKey}
          className="absolute start-0 z-10 mt-1 min-w-[10rem] rounded border border-outline-variant bg-surface-container-lowest py-1 shadow-md"
        >
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={() => choose(onFile)}
            className="block w-full px-4 py-2 text-start text-body-md text-on-surface hover:bg-surface-container focus:bg-surface-container"
          >
            {t('addFile')}
          </button>
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={() => choose(onLink)}
            className="block w-full px-4 py-2 text-start text-body-md text-on-surface hover:bg-surface-container focus:bg-surface-container"
          >
            {t('addLink')}
          </button>
        </div>
      )}
    </div>
  )
}

export function WorkAttachments({
  heading,
  files,
  links,
  edit,
}: {
  heading: string
  files: FileMeta[]
  links: LinkMeta[]
  /** The student's own draft only: adds the "+ Add" menu and remove. */
  edit?: {
    assignmentId: string
    onChange: (files: FileMeta[], links: LinkMeta[]) => void
  }
}) {
  const t = useTranslations('classroom.files')
  const fileInput = useRef<HTMLInputElement>(null)
  const linkInput = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const linkId = useId()
  const [busy, setBusy] = useState(false)
  const [linking, setLinking] = useState(false)
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (linking) linkInput.current?.focus()
  }, [linking])

  if (files.length === 0 && links.length === 0 && !edit) return null

  const items = [
    ...files.map((f) => ({ kind: 'file' as const, at: f.created_at, file: f })),
    ...links.map((l) => ({ kind: 'link' as const, at: l.created_at, link: l })),
  ].sort((a, b) => a.at.localeCompare(b.at))

  async function addFile(file: File) {
    setError(null)
    const early = earlyRefusal(file)
    if (early) {
      setError(t(early))
    } else {
      setBusy(true)
      try {
        const stored = await uploadSubmissionFile(edit!.assignmentId, file)
        edit!.onChange([...files, stored], links)
      } catch (caught) {
        setError(t(fileErrorKey(caught, 'uploadFailed')))
      } finally {
        setBusy(false)
      }
    }
    if (fileInput.current) fileInput.current.value = ''
  }

  async function addLink(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    const value = url.trim()
    if (!isHttpsLink(value)) {
      setError(t('linkInvalid'))
      return
    }
    setBusy(true)
    try {
      const stored = await addSubmissionLink(edit!.assignmentId, value)
      // Adding a link already there returns that link: keep the list unique.
      edit!.onChange(files, [...links.filter((l) => l.id !== stored.id), stored])
      setUrl('')
      setLinking(false)
    } catch (caught) {
      let key = 'linkFailed'
      if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
        const reason = caught.details.reason as LinkRefusalReason | undefined
        if (caught.fieldErrors().url) key = 'linkInvalid'
        else if (reason && LINK_REASON_KEY[reason]) key = LINK_REASON_KEY[reason]
      }
      setError(t(key))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4">
      <p className={LABEL}>{heading}</p>
      {items.length > 0 && (
        <ul className="divide-y divide-outline-variant rounded border border-outline-variant">
          {items.map((item) =>
            item.kind === 'file' ? (
              <FileItem
                key={`f-${item.file.id}`}
                file={item.file}
                busy={busy}
                download={(f) => downloadSubmissionFile(f.id)}
                view={(f) => viewSubmissionFile(f.id)}
                remove={
                  edit &&
                  (async (gone) => {
                    await deleteSubmissionFile(gone.id)
                    edit.onChange(
                      files.filter((f) => f.id !== gone.id),
                      links,
                    )
                  })
                }
                onError={setError}
              />
            ) : (
              <LinkItem
                key={`l-${item.link.id}`}
                link={item.link}
                remove={
                  edit &&
                  (async (gone) => {
                    await deleteSubmissionLink(gone.id)
                    edit.onChange(
                      files,
                      links.filter((l) => l.id !== gone.id),
                    )
                  })
                }
                onError={setError}
              />
            ),
          )}
        </ul>
      )}
      {edit && (
        <div className="mt-2">
          <input
            ref={fileInput}
            id={inputId}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-label={t('addFile')}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void addFile(file)
            }}
          />
          {linking ? (
            <form onSubmit={addLink} noValidate className="space-y-2">
              <label htmlFor={linkId} className={LABEL}>
                {t('linkLabel')}
              </label>
              <input
                ref={linkInput}
                id={linkId}
                type="url"
                inputMode="url"
                value={url}
                maxLength={2048}
                placeholder="https://"
                onChange={(e) => setUrl(e.target.value)}
                className={`force-ltr ${FIELD}`}
              />
              <div className="flex flex-wrap gap-3">
                <button type="submit" disabled={busy} className={SECONDARY_BUTTON}>
                  {busy ? t('adding') : t('addLinkButton')}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  className={SECONDARY_BUTTON}
                  onClick={() => {
                    setLinking(false)
                    setUrl('')
                    setError(null)
                  }}
                >
                  {t('cancel')}
                </button>
              </div>
            </form>
          ) : (
            <>
              <AddMenu
                disabled={busy}
                onFile={() => fileInput.current?.click()}
                onLink={() => setLinking(true)}
              />
              {busy && (
                <span role="status" className="ms-3 text-body-sm text-on-surface-variant">
                  {t('uploading')}
                </span>
              )}
              <p className="mt-1 text-body-sm text-on-surface-variant">{t('workHint')}</p>
            </>
          )}
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
