import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { ChatMessage, ChatPage, PeopleResponse, SpaceDetail } from '@/lib/api/types'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { ChatTab } from './ChatTab'

/**
 * The class chat. What must hold: everyone is told the chat is class-public;
 * names come from the roster and the TEACHER badge from the owner's id — never
 * from a name, so a student calling themselves "Sir Ahmed" gets none; bodies are
 * plain text; a student who cannot post is told why (muted, locked, archived),
 * including when a post is refused before the next poll; a draft survives a
 * failed send; only the teacher deletes (and keeps reading what they deleted)
 * and locks the chat.
 */

const getMessages = vi.fn()
const postMessage = vi.fn()
const deleteMessage = vi.fn()
const getPeople = vi.fn()
const updateSpace = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  getMessages: (...a: unknown[]) => getMessages(...a),
  postMessage: (...a: unknown[]) => postMessage(...a),
  deleteMessage: (...a: unknown[]) => deleteMessage(...a),
  getPeople: (...a: unknown[]) => getPeople(...a),
  updateSpace: (...a: unknown[]) => updateSpace(...a),
}))

const LOADED = { timeout: 5_000 }
const c = en.classroom.chat

function msg(id: string, author: string, body: string, minute = 0): ChatMessage {
  return {
    id,
    author_id: author,
    body,
    created_at: `2026-10-05T09:${String(minute).padStart(2, '0')}:00Z`,
    deleted: false,
  }
}

function page(overrides: Partial<ChatPage> = {}): ChatPage {
  return {
    messages: [],
    deleted_ids: [],
    older_cursor: null,
    server_time: '2026-10-05T10:00:00+00:00',
    reset: false,
    chat_locked: false,
    can_post: true,
    muted: false,
    ...overrides,
  }
}

const people: PeopleResponse = {
  owner: { user_id: 't-1', full_name: 'Sir Ahmed' },
  members: [
    {
      user_id: 's-1',
      full_name: 'Ayesha Khan',
      joined_at: '2026-10-01T00:00:00Z',
      muted: null,
    },
    // A student who chose the teacher's name.
    { user_id: 's-2', full_name: 'Sir Ahmed', joined_at: '2026-10-01T00:00:00Z', muted: null },
  ],
}

function renderChat(
  props: Partial<React.ComponentProps<typeof ChatTab>> = {},
  locale = 'en',
  messages: typeof en = en,
  onError?: () => void,
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      {...(onError ? { onError } : {})}
    >
      <ChatTab
        spaceId="space-1"
        isOwner={false}
        archived={false}
        onSpaceChange={() => {}}
        {...props}
      />
    </NextIntlClientProvider>,
  )
}

const item = (text: string) => screen.getByText(text).closest('li')!

beforeEach(() => {
  vi.clearAllMocks()
  getPeople.mockResolvedValue(people)
  getMessages.mockResolvedValue(
    page({
      messages: [
        msg('m1', 't-1', 'Test on Monday', 1),
        msg('m2', 's-2', 'I am the teacher now', 2),
        msg('m3', 's-1', '<b>not bold</b>', 3),
      ],
    }),
  )
})

describe('reading', () => {
  it('says the chat is class-public and shows names from the roster', async () => {
    renderChat()
    expect(await screen.findByText('Test on Monday', {}, LOADED)).toBeInTheDocument()
    expect(screen.getByText(c.intro)).toBeInTheDocument()
    expect(within(item('<b>not bold</b>')).getByText('Ayesha Khan')).toBeInTheDocument()
  })

  it("badges the teacher by the owner's id, never by a name", async () => {
    renderChat()
    await screen.findByText('Test on Monday', {}, LOADED)
    expect(within(item('Test on Monday')).getByText(c.teacherBadge)).toBeInTheDocument()
    expect(within(item('I am the teacher now')).queryByText(c.teacherBadge)).toBeNull()
  })

  it('names an author who has left as a former member, after one roster refresh', async () => {
    getMessages.mockResolvedValue(page({ messages: [msg('m9', 's-gone', 'bye')] }))
    renderChat()
    expect(
      await within(await screen.findByRole('log', {}, LOADED)).findByText(c.formerMember),
    ).toBeInTheDocument()
    expect(getPeople).toHaveBeenCalledTimes(2)
  })

  it('shows an empty chat as an invitation, not an error', async () => {
    getMessages.mockResolvedValue(page())
    renderChat()
    expect(await screen.findByText(c.empty, {}, LOADED)).toBeInTheDocument()
  })

  it('offers no delete and no lock to a student', async () => {
    renderChat()
    await screen.findByText('Test on Monday', {}, LOADED)
    expect(screen.queryByRole('button', { name: c.delete })).toBeNull()
    expect(screen.queryByRole('button', { name: c.lock })).toBeNull()
  })
})

describe('posting', () => {
  it('sends the trimmed text, shows it at once and clears the box', async () => {
    postMessage.mockResolvedValue(msg('m10', 's-1', 'Thank you', 10))
    renderChat()
    const box = await screen.findByLabelText(c.composerLabel, {}, LOADED)
    await userEvent.type(box, '  Thank you ')
    await userEvent.click(screen.getByRole('button', { name: c.send }))
    expect(postMessage).toHaveBeenCalledWith('space-1', 'Thank you')
    expect(await screen.findByText('Thank you')).toBeInTheDocument()
    expect(box).toHaveValue('')
  })

  it('sends on Enter and starts a new line on Shift+Enter', async () => {
    postMessage.mockResolvedValue(msg('m10', 's-1', 'line one\nline two', 10))
    renderChat()
    const box = await screen.findByLabelText(c.composerLabel, {}, LOADED)
    await userEvent.type(box, 'line one{Shift>}{Enter}{/Shift}line two')
    expect(postMessage).not.toHaveBeenCalled()
    await userEvent.type(box, '{Enter}')
    expect(postMessage).toHaveBeenCalledWith('space-1', 'line one\nline two')
  })

  it.each([
    [{ muted: true, can_post: false }, false, c.muted],
    [{ chat_locked: true, can_post: false }, false, c.locked],
    [{ can_post: false }, true, c.archived],
  ])('tells a student why they cannot post (%o)', async (state, archived, why) => {
    getMessages.mockResolvedValue(page(state))
    renderChat({ archived })
    expect(await screen.findByText(why, {}, LOADED)).toBeInTheDocument()
    expect(screen.queryByLabelText(c.composerLabel)).toBeNull()
  })

  it('explains a post refused before the next poll noticed', async () => {
    postMessage.mockRejectedValue(
      new ApiError(400, 'VALIDATION_ERROR', 'locked', { reason: 'chat_locked' }),
    )
    renderChat()
    await userEvent.type(await screen.findByLabelText(c.composerLabel, {}, LOADED), 'Hello?')
    await userEvent.click(screen.getByRole('button', { name: c.send }))
    expect(await screen.findByText(c.locked)).toBeInTheDocument()
  })

  it('says how long to wait when sending too fast, and keeps the draft', async () => {
    postMessage.mockRejectedValue(
      new ApiError(429, 'RATE_LIMITED', 'slow', { retry_after: 42 }),
    )
    renderChat()
    const box = await screen.findByLabelText(c.composerLabel, {}, LOADED)
    await userEvent.type(box, 'again')
    await userEvent.click(screen.getByRole('button', { name: c.send }))
    expect(
      await screen.findByText('You are sending messages too quickly. Try again in 42 seconds.'),
    ).toBeInTheDocument()
    expect(box).toHaveValue('again')
  })

  it('keeps the draft when sending fails', async () => {
    postMessage.mockRejectedValue(new TypeError('offline'))
    renderChat()
    const box = await screen.findByLabelText(c.composerLabel, {}, LOADED)
    await userEvent.type(box, 'still here')
    await userEvent.click(screen.getByRole('button', { name: c.send }))
    expect(await screen.findByText(c.sendFailed)).toBeInTheDocument()
    expect(box).toHaveValue('still here')
  })
})

describe('the teacher', () => {
  it('deletes after confirming, and keeps reading what was deleted', async () => {
    deleteMessage.mockResolvedValue(undefined)
    renderChat({ isOwner: true })
    await screen.findByText('I am the teacher now', {}, LOADED)
    await userEvent.click(
      within(item('I am the teacher now')).getByRole('button', { name: c.delete }),
    )
    const confirm = screen.getByRole('alertdialog', { name: c.deleteConfirm })
    await userEvent.click(within(confirm).getByRole('button', { name: c.delete }))
    expect(deleteMessage).toHaveBeenCalledWith('m2')
    expect(
      await within(item('I am the teacher now')).findByText(c.deletedNote),
    ).toBeInTheDocument()
    expect(
      within(item('I am the teacher now')).queryByRole('button', { name: c.delete }),
    ).toBeNull()
  })

  it('locks the chat and can still post', async () => {
    const onSpaceChange = vi.fn()
    updateSpace.mockResolvedValue({ id: 'space-1', chat_locked: true } as SpaceDetail)
    getMessages.mockResolvedValue(page())
    renderChat({ isOwner: true, onSpaceChange })
    await userEvent.click(await screen.findByRole('button', { name: c.lock }, LOADED))
    expect(updateSpace).toHaveBeenCalledWith('space-1', { chat_locked: true })
    expect(await screen.findByText(c.lockedOwner)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: c.unlock })).toBeInTheDocument()
    expect(screen.getByLabelText(c.composerLabel)).toBeInTheDocument()
    expect(onSpaceChange).toHaveBeenCalledWith({ id: 'space-1', chat_locked: true })
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders the teacher view fully in %s with no missing keys', async (locale, messages) => {
    const onError = vi.fn()
    getMessages.mockResolvedValue(
      page({
        chat_locked: true,
        messages: [{ ...msg('m1', 's-1', 'hello'), deleted: true }, msg('m2', 's-gone', 'bye')],
        older_cursor: 'c1',
      }),
    )
    renderChat({ isOwner: true }, locale, messages as typeof en, onError)
    await screen.findByText('hello', {}, LOADED)
    await waitFor(() => expect(getPeople).toHaveBeenCalledTimes(2))
    expect(onError).not.toHaveBeenCalled()
  })
})
