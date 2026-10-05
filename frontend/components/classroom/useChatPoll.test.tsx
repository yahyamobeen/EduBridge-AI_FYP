import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/api/errors'
import type { ChatMessage, ChatPage } from '@/lib/api/types'
import { POLL_MS, useChatPoll } from './useChatPoll'

/**
 * The chat poll. What must hold: polls never overlap and stop while the tab is
 * hidden; a shown tab catches up at once; the overlap window's duplicates are
 * merged by id; a deletion removes a member's copy and marks the teacher's; a
 * 429 is waited out for as long as the server says; a 403 stops polling; the
 * cursor is the server's clock, never this device's.
 */

const getMessages = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  getMessages: (...a: unknown[]) => getMessages(...a),
}))

function msg(id: string, at: string, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id,
    author_id: 's-1',
    body: `body ${id}`,
    created_at: at,
    deleted: false,
    ...overrides,
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

let hidden = false
function setHidden(value: boolean) {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

const ids = (messages: ChatMessage[]) => messages.map((m) => m.id)

beforeEach(() => {
  vi.useFakeTimers()
  getMessages.mockReset()
  hidden = false
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useChatPoll', () => {
  it('loads the newest page, then catches up from the server clock every few seconds', async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('m1', '2026-10-05T09:59:00Z')] }))
      .mockResolvedValue(page({ server_time: '2026-10-05T10:00:05+00:00' }))
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()

    expect(getMessages).toHaveBeenCalledTimes(1)
    expect(getMessages.mock.calls[0]!.slice(0, 2)).toEqual(['sp-1', {}])
    expect(ids(result.current.messages)).toEqual(['m1'])
    expect(result.current.status).toEqual({ canPost: true, locked: false, muted: false })

    await advance(POLL_MS - 1)
    expect(getMessages).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(getMessages).toHaveBeenCalledTimes(2)
    expect(getMessages.mock.calls[1]![1]).toEqual({ after: '2026-10-05T10:00:00+00:00' })
    await advance(POLL_MS)
    expect(getMessages.mock.calls[2]![1]).toEqual({ after: '2026-10-05T10:00:05+00:00' })
  })

  it('never starts a poll while the previous one is still waiting', async () => {
    let answer: (p: ChatPage) => void = () => {}
    getMessages.mockResolvedValueOnce(page()).mockImplementationOnce(
      () =>
        new Promise<ChatPage>((resolve) => {
          answer = resolve
        }),
    )
    renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(getMessages).toHaveBeenCalledTimes(2)
    await advance(POLL_MS * 4) // a very slow answer
    expect(getMessages).toHaveBeenCalledTimes(2)
    getMessages.mockResolvedValue(page())
    await act(async () => answer(page()))
    await advance(POLL_MS)
    expect(getMessages).toHaveBeenCalledTimes(3)
  })

  it('does not poll while hidden and catches up the moment it is shown', async () => {
    getMessages.mockResolvedValue(page())
    renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    act(() => setHidden(true))
    await advance(POLL_MS * 6)
    expect(getMessages).toHaveBeenCalledTimes(1)

    act(() => setHidden(false))
    await flush()
    expect(getMessages).toHaveBeenCalledTimes(2)
    expect(getMessages.mock.calls[1]![1]).toEqual({ after: '2026-10-05T10:00:00+00:00' })
  })

  it('merges the overlap window by id and keeps messages in time order', async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('m2', '2026-10-05T09:59:02Z')] }))
      .mockResolvedValueOnce(
        page({
          messages: [msg('m1', '2026-10-05T09:59:01Z'), msg('m2', '2026-10-05T09:59:02Z')],
        }),
      )
      .mockResolvedValue(page())
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(ids(result.current.messages)).toEqual(['m1', 'm2'])
  })

  it("removes a deleted message from a member's screen", async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('m1', '2026-10-05T09:59:00Z')] }))
      .mockResolvedValue(page({ deleted_ids: ['m1'] }))
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(result.current.messages).toEqual([])
  })

  it("keeps a deleted message on the teacher's screen, marked deleted", async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('m1', '2026-10-05T09:59:00Z')] }))
      .mockResolvedValue(page({ deleted_ids: ['m1'] }))
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: true }))
    await flush()
    await advance(POLL_MS)
    expect(result.current.messages.map((m) => [m.id, m.deleted])).toEqual([['m1', true]])
  })

  it('starts again from the newest page when the server says it fell too far behind', async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('old', '2026-10-05T08:00:00Z')] }))
      .mockResolvedValue(
        page({
          reset: true,
          messages: [msg('new', '2026-10-05T10:00:00Z')],
          older_cursor: 'c1',
        }),
      )
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(ids(result.current.messages)).toEqual(['new'])
    expect(result.current.olderCursor).toBe('c1')
  })

  it('waits out a 429 for as long as the server says', async () => {
    getMessages
      .mockResolvedValueOnce(page())
      .mockRejectedValueOnce(new ApiError(429, 'RATE_LIMITED', 'slow', { retry_after: 20 }))
      .mockResolvedValue(page())
    renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(getMessages).toHaveBeenCalledTimes(2)
    await advance(19_000)
    expect(getMessages).toHaveBeenCalledTimes(2)
    await advance(1_000)
    expect(getMessages).toHaveBeenCalledTimes(3)
  })

  it('stops polling on a 403 and says the chat is unavailable', async () => {
    getMessages
      .mockResolvedValueOnce(page())
      .mockRejectedValue(new ApiError(403, 'FORBIDDEN_SCOPE', 'no'))
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(result.current.failed).toBe(true)
    await advance(POLL_MS * 5)
    expect(getMessages).toHaveBeenCalledTimes(2)
  })

  it('keeps polling through a network failure without losing what is shown', async () => {
    getMessages
      .mockResolvedValueOnce(page({ messages: [msg('m1', '2026-10-05T09:59:00Z')] }))
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValue(page())
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await advance(POLL_MS)
    expect(ids(result.current.messages)).toEqual(['m1'])
    expect(result.current.failed).toBe(false)
    await advance(POLL_MS)
    expect(getMessages).toHaveBeenCalledTimes(3)
  })

  it('loads older messages in front, without duplicates', async () => {
    getMessages
      .mockResolvedValueOnce(
        page({ messages: [msg('m3', '2026-10-05T09:59:03Z')], older_cursor: 'c1' }),
      )
      .mockResolvedValueOnce(
        page({
          messages: [msg('m1', '2026-10-05T09:59:01Z'), msg('m3', '2026-10-05T09:59:03Z')],
        }),
      )
    const { result } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    await act(async () => {
      await result.current.loadOlder()
    })
    expect(getMessages.mock.calls[1]!.slice(0, 2)).toEqual(['sp-1', { before: 'c1' }])
    expect(ids(result.current.messages)).toEqual(['m1', 'm3'])
    expect(result.current.olderCursor).toBeNull()
  })

  it('stops polling when the screen goes away', async () => {
    getMessages.mockResolvedValue(page())
    const { unmount } = renderHook(() => useChatPoll('sp-1', { isOwner: false }))
    await flush()
    unmount()
    await advance(POLL_MS * 5)
    expect(getMessages).toHaveBeenCalledTimes(1)
  })
})
