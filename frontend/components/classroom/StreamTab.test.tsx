import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { Announcement } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { StreamTab } from './StreamTab'

/**
 * The stream. What must hold: a member gets no composer and no edit/delete; a
 * scheduled post goes out with an ISO instant carrying an offset (the backend
 * refuses a naive one); the owner sees the "Scheduled for" badge; and "Load
 * older" sends the cursor and never duplicates a post.
 */

const listAnnouncements = vi.fn()
const createAnnouncement = vi.fn()
const updateAnnouncement = vi.fn()
const deleteAnnouncement = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  listAnnouncements: (...a: unknown[]) => listAnnouncements(...a),
  createAnnouncement: (...a: unknown[]) => createAnnouncement(...a),
  updateAnnouncement: (...a: unknown[]) => updateAnnouncement(...a),
  deleteAnnouncement: (...a: unknown[]) => deleteAnnouncement(...a),
}))

function post(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: 'a-1',
    body: 'Test on Monday',
    author_id: 't-1',
    publish_at: '2026-10-04T09:00:00Z',
    scheduled: false,
    created_at: '2026-10-04T09:00:00Z',
    updated_at: '2026-10-04T09:00:00Z',
    ...overrides,
  }
}

function renderStream(props: Partial<React.ComponentProps<typeof StreamTab>> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="Asia/Karachi">
      <StreamTab
        spaceId="space-1"
        isOwner={false}
        canPost={false}
        authorName="Sir Ahmed"
        {...props}
      />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listAnnouncements.mockResolvedValue({ items: [post()], next_cursor: null })
})

describe('a member', () => {
  it('reads posts as plain text, with no composer and no edit or delete', async () => {
    listAnnouncements.mockResolvedValue({
      items: [post({ body: '<b>not bold</b>' })],
      next_cursor: null,
    })
    renderStream()
    expect(await screen.findByText('<b>not bold</b>')).toBeInTheDocument()
    expect(screen.queryByLabelText(en.classroom.stream.composerLabel)).toBeNull()
    expect(screen.queryByRole('button', { name: en.classroom.stream.edit })).toBeNull()
    expect(screen.queryByRole('button', { name: en.classroom.stream.delete })).toBeNull()
  })

  it('loads older posts with the cursor, without duplicating any', async () => {
    listAnnouncements
      .mockResolvedValueOnce({ items: [post({ id: 'a-2', body: 'newer' })], next_cursor: 'c1' })
      .mockResolvedValueOnce({
        items: [post({ id: 'a-2', body: 'newer' }), post({ id: 'a-1', body: 'older' })],
        next_cursor: null,
      })
    renderStream()
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.stream.loadOlder }),
    )
    expect(listAnnouncements).toHaveBeenLastCalledWith('space-1', 'c1')
    expect(await screen.findByText('older')).toBeInTheDocument()
    expect(screen.getAllByText('newer')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: en.classroom.stream.loadOlder })).toBeNull()
  })
})

describe('the owner', () => {
  it('posts now without a publish time', async () => {
    createAnnouncement.mockResolvedValue(post({ id: 'a-9', body: 'Bring calculators' }))
    renderStream({ isOwner: true, canPost: true })
    await userEvent.type(
      await screen.findByLabelText(en.classroom.stream.composerLabel),
      '  Bring calculators ',
    )
    await userEvent.click(screen.getByRole('button', { name: en.classroom.stream.post }))
    expect(createAnnouncement).toHaveBeenCalledWith('space-1', { body: 'Bring calculators' })
    expect(await screen.findByText('Bring calculators')).toBeInTheDocument()
  })

  it('schedules with an ISO instant and shows the badge', async () => {
    createAnnouncement.mockResolvedValue(
      post({ id: 'a-9', body: 'Later', scheduled: true, publish_at: '2030-01-01T05:00:00Z' }),
    )
    renderStream({ isOwner: true, canPost: true })
    await userEvent.type(
      await screen.findByLabelText(en.classroom.stream.composerLabel),
      'Later',
    )
    await userEvent.click(screen.getByLabelText(en.classroom.stream.scheduleLater))
    await userEvent.type(
      screen.getByLabelText(en.classroom.stream.scheduleLabel),
      '2030-01-01T10:00',
    )
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.stream.scheduleButton }),
    )
    const [, body] = createAnnouncement.mock.calls[0]!
    expect(body.body).toBe('Later')
    expect(body.publish_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    expect(await screen.findByText(/Scheduled for/)).toBeInTheDocument()
  })

  it('explains a schedule the server refused', async () => {
    createAnnouncement.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'x', { fields: { publish_at: 'past' } }),
    )
    renderStream({ isOwner: true, canPost: true })
    await userEvent.type(await screen.findByLabelText(en.classroom.stream.composerLabel), 'x')
    await userEvent.click(screen.getByLabelText(en.classroom.stream.scheduleLater))
    await userEvent.type(
      screen.getByLabelText(en.classroom.stream.scheduleLabel),
      '2030-01-01T10:00',
    )
    await userEvent.click(
      screen.getByRole('button', { name: en.classroom.stream.scheduleButton }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      en.classroom.stream.scheduleInvalid,
    )
  })

  it('deletes only after confirming', async () => {
    deleteAnnouncement.mockResolvedValue(undefined)
    renderStream({ isOwner: true, canPost: true })
    await userEvent.click(
      await screen.findByRole('button', { name: en.classroom.stream.delete }),
    )
    expect(deleteAnnouncement).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: en.classroom.stream.delete }),
    )
    expect(deleteAnnouncement).toHaveBeenCalledWith('a-1')
    await waitFor(() => expect(screen.queryByText('Test on Monday')).toBeNull())
  })

  it('cannot post into an archived classroom, and is told why', async () => {
    renderStream({ isOwner: true, canPost: false })
    expect(await screen.findByText(en.classroom.stream.archivedNoPosting)).toBeInTheDocument()
    expect(screen.queryByLabelText(en.classroom.stream.composerLabel)).toBeNull()
    expect(screen.queryByRole('button', { name: en.classroom.stream.edit })).toBeNull()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders the owner stream fully in %s with no missing keys', async (locale, messages) => {
    const onError = vi.fn()
    listAnnouncements.mockResolvedValue({
      items: [post({ scheduled: true, updated_at: '2026-10-04T10:00:00Z' })],
      next_cursor: 'more',
    })
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={messages as typeof en}
        timeZone="Asia/Karachi"
        onError={onError}
      >
        <StreamTab spaceId="space-1" isOwner canPost authorName="Sir Ahmed" />
      </NextIntlClientProvider>,
    )
    expect(await screen.findByText('Test on Monday')).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalled()
  })
})
