import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { FileMeta, LinkMeta } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { WorkAttachments } from './WorkAttachments'

/**
 * A student's files and links (classroom Phase 6b). What must hold: one list in
 * the order things were added; one "+ Add" menu (File / Link) that works from
 * the keyboard; a link that is not https never reaches the server and never
 * renders as an anchor; a refusal is explained by `details`, never `message`;
 * removing asks first; and the read-only view offers nothing to change.
 */

const addSubmissionLink = vi.fn()
const deleteSubmissionLink = vi.fn()
const uploadSubmissionFile = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  addSubmissionLink: (...a: unknown[]) => addSubmissionLink(...a),
  deleteSubmissionLink: (...a: unknown[]) => deleteSubmissionLink(...a),
  uploadSubmissionFile: (...a: unknown[]) => uploadSubmissionFile(...a),
  deleteSubmissionFile: vi.fn(),
  downloadSubmissionFile: vi.fn(),
  viewSubmissionFile: vi.fn(),
}))

const FILE: FileMeta = {
  id: 'f-1',
  filename: 'Lab report.pdf',
  content_type: 'application/pdf',
  size_bytes: 2_000,
  created_at: '2026-10-05T08:00:00Z',
}
const LINK: LinkMeta = {
  id: 'l-1',
  url: 'https://docs.example.com/my-lab',
  created_at: '2026-10-05T08:30:00Z',
}

const onChange = vi.fn()

function renderWork(
  { files = [FILE], links = [LINK], editable = true } = {},
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
      <WorkAttachments
        heading="Your files and links"
        files={files}
        links={links}
        edit={editable ? { assignmentId: 'as-1', onChange } : undefined}
      />
    </NextIntlClientProvider>,
  )
  return errors
}

const menuButton = () => screen.getByRole('button', { name: en.classroom.files.addMenu })

beforeEach(() => vi.clearAllMocks())

describe('the list', () => {
  it('holds files and links together, in the order they were added', () => {
    const later: FileMeta = {
      ...FILE,
      id: 'f-2',
      filename: 'Later.pdf',
      created_at: '2026-10-05T09:00:00Z',
    }
    renderWork({ files: [FILE, later] })
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toContain('Lab report.pdf')
    expect(items[1]).toContain('https://docs.example.com/my-lab')
    expect(items[2]).toContain('Later.pdf')
  })

  it('renders a link as an anchor that opens safely, and never a non-https one', () => {
    renderWork({ links: [LINK, { ...LINK, id: 'l-2', url: 'javascript:alert(1)' }] })
    expect(screen.getByRole('link', { name: LINK.url })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(screen.queryByRole('link', { name: 'javascript:alert(1)' })).toBeNull()
  })

  it('offers nothing to change when read-only', () => {
    renderWork({ editable: false })
    expect(screen.queryByRole('button', { name: en.classroom.files.addMenu })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Remove/ })).toBeNull()
  })
})

describe('the "+ Add" menu', () => {
  it('works from the keyboard and gives focus back on Escape', async () => {
    renderWork()
    menuButton().focus()
    await userEvent.keyboard('{ArrowDown}')
    const menu = screen.getByRole('menu')
    const [file, link] = within(menu).getAllByRole('menuitem')
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')
    expect(file).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(link).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(file).toHaveFocus() // wraps
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(menuButton()).toHaveFocus()
  })

  it('closes on a click elsewhere', async () => {
    renderWork()
    await userEvent.click(menuButton())
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('File opens the picker, and an upload joins the list', async () => {
    const click = vi.spyOn(HTMLInputElement.prototype, 'click')
    renderWork()
    await userEvent.click(menuButton())
    await userEvent.click(screen.getByRole('menuitem', { name: en.classroom.files.addFile }))
    expect(click).toHaveBeenCalled()
    click.mockRestore()

    const stored = { ...FILE, id: 'f-2', filename: 'Data.pdf' }
    uploadSubmissionFile.mockResolvedValue(stored)
    await userEvent.upload(
      screen.getByLabelText(en.classroom.files.addFile),
      new File([new Uint8Array(10)], 'data.pdf'),
    )
    expect(uploadSubmissionFile).toHaveBeenCalledWith('as-1', expect.any(File))
    expect(onChange).toHaveBeenCalledWith([FILE, stored], [LINK])
  })
})

describe('adding a link', () => {
  async function openLinkForm() {
    renderWork()
    await userEvent.click(menuButton())
    await userEvent.click(screen.getByRole('menuitem', { name: en.classroom.files.addLink }))
    return screen.getByLabelText(en.classroom.files.linkLabel)
  }

  it('never sends a link that is not https', async () => {
    const input = await openLinkForm()
    expect(input).toHaveFocus()
    await userEvent.type(input, 'http://example.com')
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.files.addLinkButton }),
    )
    expect(screen.getByRole('alert')).toHaveTextContent(en.classroom.files.linkInvalid)
    expect(addSubmissionLink).not.toHaveBeenCalled()
  })

  it('adds an https link and closes the form', async () => {
    const stored = { ...LINK, id: 'l-2', url: 'https://slides.example.com/deck' }
    addSubmissionLink.mockResolvedValue(stored)
    const input = await openLinkForm()
    await userEvent.type(input, '  https://slides.example.com/deck ')
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.files.addLinkButton }),
    )
    expect(addSubmissionLink).toHaveBeenCalledWith('as-1', 'https://slides.example.com/deck')
    expect(onChange).toHaveBeenCalledWith([FILE], [LINK, stored])
    expect(screen.queryByLabelText(en.classroom.files.linkLabel)).toBeNull()
  })

  it("explains the server's refusal by its reason", async () => {
    addSubmissionLink.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { reason: 'too_many_links' }),
    )
    const input = await openLinkForm()
    await userEvent.type(input, 'https://example.com/6')
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.files.addLinkButton }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(en.classroom.files.tooManyLinks)
  })
})

describe('removing a link', () => {
  it('asks first, then removes', async () => {
    deleteSubmissionLink.mockResolvedValue(undefined)
    renderWork()
    await userEvent.click(screen.getByRole('button', { name: `Remove link ${LINK.url}` }))
    expect(deleteSubmissionLink).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: en.classroom.files.remove }),
    )
    expect(deleteSubmissionLink).toHaveBeenCalledWith('l-1')
    expect(onChange).toHaveBeenCalledWith([FILE], [])
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])(
    'renders the list, the menu and the link form in %s with no missing keys',
    async (locale, messages) => {
      const m = messages as typeof en
      const errors = renderWork({}, locale, m)
      await userEvent.click(screen.getByRole('button', { name: m.classroom.files.addMenu }))
      await userEvent.click(screen.getByRole('menuitem', { name: m.classroom.files.addLink }))
      expect(errors).not.toHaveBeenCalled()
    },
  )
})
