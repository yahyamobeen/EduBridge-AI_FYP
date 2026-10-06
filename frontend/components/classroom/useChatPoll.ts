'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getMessages } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { ChatMessage, ChatPage } from '@/lib/api/types'

export const POLL_MS = 5_000

export type ChatStatus = { canPost: boolean; locked: boolean; muted: boolean }

function byTime(a: ChatMessage, b: ChatMessage): number {
  return Date.parse(a.created_at) - Date.parse(b.created_at) || a.id.localeCompare(b.id)
}

/**
 * The class chat's poll (tdd.md §3.6, classroom Phase 7).
 *
 * - A `setTimeout` CHAIN, never `setInterval`: on a slow connection two polls
 *   never overlap.
 * - The cursor is the server's `server_time` — the DATABASE clock — never this
 *   device's, which may be minutes wrong.
 * - Each catch-up re-reads an overlap window, so the same message can arrive
 *   twice: everything is merged by id.
 * - A hidden tab does not poll; it catches up the moment it is shown again.
 * - A message deleted since the last poll arrives as an id: a member's copy is
 *   removed, the teacher's is marked deleted (they keep reading it).
 * - A 429 waits as long as the server says; a 403 (removed, gated, archived
 *   away from) stops polling.
 */
export function useChatPoll(spaceId: string, { isOwner }: { isOwner: boolean }) {
  const [messages, setMessages] = useState<Map<string, ChatMessage>>(() => new Map())
  const [status, setStatus] = useState<ChatStatus | null>(null)
  const [olderCursor, setOlderCursor] = useState<string | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [failed, setFailed] = useState(false)
  const cursor = useRef<string | null>(null)

  const merge = useCallback(
    (page: ChatPage) => {
      const fresh = page.reset || cursor.current === null
      setMessages((prev) => {
        const next = fresh ? new Map<string, ChatMessage>() : new Map(prev)
        for (const m of page.messages) next.set(m.id, m)
        for (const id of page.deleted_ids) {
          const kept = next.get(id)
          if (isOwner && kept) next.set(id, { ...kept, deleted: true })
          else next.delete(id)
        }
        return next
      })
      if (fresh) setOlderCursor(page.older_cursor)
      cursor.current = page.server_time
      setStatus({ canPost: page.can_post, locked: page.chat_locked, muted: page.muted })
    },
    [isOwner],
  )

  useEffect(() => {
    cursor.current = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let stopped = false
    const controller = new AbortController()

    const tick = async () => {
      if (stopped || document.hidden) return
      let delay = POLL_MS
      try {
        merge(
          await getMessages(
            spaceId,
            cursor.current ? { after: cursor.current } : {},
            controller.signal,
          ),
        )
      } catch (e) {
        if (stopped) return
        if (e instanceof ApiError && e.status === 403) {
          stopped = true
          setFailed(true)
          return
        }
        if (e instanceof ApiError && e.code === 'RATE_LIMITED') {
          const seconds = Number(e.details.retry_after ?? 0)
          delay = Math.max(POLL_MS, seconds * 1000)
        } else if (cursor.current === null) {
          setFailed(true)
        }
        // Anything else: keep what is on screen and try again next time.
      }
      if (!stopped && !document.hidden) timer = setTimeout(tick, delay)
    }

    const onVisibility = () => {
      if (timer) clearTimeout(timer)
      timer = null
      if (!document.hidden) void tick()
    }

    void tick()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stopped = true
      controller.abort()
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [spaceId, merge])

  const loadOlder = useCallback(async () => {
    if (!olderCursor) return
    setLoadingOlder(true)
    try {
      const page = await getMessages(spaceId, { before: olderCursor })
      setMessages((prev) => {
        const next = new Map(prev)
        for (const m of page.messages) if (!next.has(m.id)) next.set(m.id, m)
        return next
      })
      setOlderCursor(page.older_cursor)
    } catch {
      // The button stays; the next press tries again.
    } finally {
      setLoadingOlder(false)
    }
  }, [spaceId, olderCursor])

  /** A message this screen just posted: shown at once, not on the next poll. */
  const add = useCallback(
    (m: ChatMessage) => setMessages((prev) => new Map(prev).set(m.id, m)),
    [],
  )

  /** The teacher just deleted it: kept on their screen, marked deleted. */
  const markDeleted = useCallback(
    (id: string) =>
      setMessages((prev) => {
        const kept = prev.get(id)
        return kept ? new Map(prev).set(id, { ...kept, deleted: true }) : prev
      }),
    [],
  )

  /** A refusal or a lock change told us the state before the next poll did. */
  const patchStatus = useCallback(
    (patch: Partial<ChatStatus>) => setStatus((s) => (s ? { ...s, ...patch } : s)),
    [],
  )

  const ordered = useMemo(() => [...messages.values()].sort(byTime), [messages])

  return {
    messages: ordered,
    status,
    failed,
    olderCursor,
    loadingOlder,
    loadOlder,
    add,
    markDeleted,
    patchStatus,
  }
}
