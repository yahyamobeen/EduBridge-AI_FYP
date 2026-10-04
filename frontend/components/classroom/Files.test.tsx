import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { FileMeta } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { FileSection } from './Files'

/**
 * The shared file list. What must hold: a download is SAVED, never opened; a
 * file certain to be refused (wrong extension, over 5 MB) never reaches the
 * server; a server refusal is explained by `details.reason`, never `message`;
 * removing asks first; and a read-only list offers neither add nor remove.
 */

const saveBlob = vi.fn()
vi.mock('@/lib/download', () => ({ saveBlob: (...a: unknown[]) => saveBlob(...a) }))

const FILE: FileMeta = {
  id: 'f-1',
  filename: 'Lab report.pdf',
  content_type: 'application/pdf',
  size_bytes: 2_500_000,
  created_at: '2026-10-05T09:00:00Z',
}

const download = vi.fn()
const upload = vi.fn()
const remove = vi.fn()
const onChange = vi.fn()

function renderFiles(
  props: Partial<React.ComponentProps<typeof FileSection>> = {},
  locale = 'en',
  messages: typeof en = en,
) {
  const errors = vi.fn()
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      onError={errors}
    >
      <FileSection
        heading="Attachments"
        files={[FILE]}
        download={download}
        onChange={onChange}
        {...props}
      />
    </NextIntlClientProvider>,
  )
  return errors
}

const pick = (name: string, bytes = 10) => new File([new Uint8Array(bytes)], name)

beforeEach(() => {
  vi.clearAllMocks()
  download.mockResolvedValue(new Blob(['%PDF']))
})

describe('reading', () => {
  it('shows each file with its size, and saves it on download', async () => {
    renderFiles()
    expect(screen.getByText('2.4 MB')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Download Lab report.pdf' }))
    expect(download).toHaveBeenCalledWith(FILE)
    expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), 'Lab report.pdf')
  })

  it('says so when a download fails', async () => {
    download.mockRejectedValue(new ApiError(403, 'FORBIDDEN_SCOPE', 'x'))
    renderFiles()
    await userEvent.click(screen.getByRole('button', { name: 'Download Lab report.pdf' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      en.classroom.files.downloadFailed,
    )
  })

  it('offers no add or remove when read-only, and renders nothing when empty', () => {
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Karachi">
        <FileSection heading="Files" files={[]} download={download} />
      </NextIntlClientProvider>,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('adding', () => {
  it('uploads and appends the stored file', async () => {
    const stored = { ...FILE, id: 'f-2', filename: 'Sheet.pdf' }
    upload.mockResolvedValue(stored)
    renderFiles({ upload })
    await userEvent.upload(screen.getByLabelText(en.classroom.files.add), pick('sheet.pdf'))
    expect(upload).toHaveBeenCalledWith(expect.any(File))
    expect(onChange).toHaveBeenCalledWith([FILE, stored])
  })

  it('never sends a file it knows will be refused', async () => {
    renderFiles({ upload })
    const input = screen.getByLabelText(en.classroom.files.add)
    await userEvent.upload(input, pick('virus.exe'), { applyAccept: false })
    expect(screen.getByRole('alert')).toHaveTextContent(en.classroom.files.unsupportedType)
    await userEvent.upload(input, pick('big.pdf', 5 * 1024 * 1024 + 1))
    expect(screen.getByRole('alert')).toHaveTextContent(en.classroom.files.tooLarge)
    expect(upload).not.toHaveBeenCalled()
  })

  it("explains the server's refusal by its reason", async () => {
    upload.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { reason: 'too_many_files' }),
    )
    renderFiles({ upload })
    await userEvent.upload(screen.getByLabelText(en.classroom.files.add), pick('a.pdf'))
    expect(await screen.findByRole('alert')).toHaveTextContent(en.classroom.files.tooManyFiles)
  })
})

describe('removing', () => {
  it('asks first, then removes', async () => {
    remove.mockResolvedValue(undefined)
    renderFiles({ remove })
    await userEvent.click(screen.getByRole('button', { name: 'Remove Lab report.pdf' }))
    expect(remove).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: en.classroom.files.remove }),
    )
    expect(remove).toHaveBeenCalledWith(FILE)
    expect(onChange).toHaveBeenCalledWith([])
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders an editable list fully in %s with no missing keys', (locale, messages) => {
    const errors = renderFiles({ upload, remove }, locale, messages as typeof en)
    expect(errors).not.toHaveBeenCalled()
  })
})
