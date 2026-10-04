'use client'

import { useCallback, useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { FormBanner } from '@/components/ui/FormFeedback'
import { listAssignments } from '@/lib/api/endpoints'
import type { AssignmentDetail, AssignmentSummary } from '@/lib/api/types'
import { AssignmentForm } from './AssignmentForm'
import { AssignmentMeta, StatusChip } from './AssignmentParts'
import { AssignmentView } from './AssignmentView'
import { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON } from './styles'

/**
 * Classwork — assignments, newest first (tdd.md §3.6, classroom Phase 4).
 *
 * Nothing here filters: a member never receives a scheduled assignment (the
 * database withholds it, as for announcements), and each member's status is
 * derived by the server. Opening an assignment replaces the list in place;
 * "Back" returns to the list as it was, kept in step with any change made
 * inside without a refetch.
 */
export function ClassworkTab({
  spaceId,
  subjectId,
  isOwner,
  canPost,
}: {
  spaceId: string
  subjectId: string
  isOwner: boolean
  /** Owner of a non-archived classroom. */
  canPost: boolean
}) {
  const t = useTranslations('classroom.classwork')
  const [items, setItems] = useState<AssignmentSummary[] | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listAssignments(spaceId, undefined, controller.signal)
      .then((page) => {
        setItems(page.items)
        setCursor(page.next_cursor)
      })
      .catch((e) => {
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [spaceId])

  async function loadOlder() {
    if (!cursor) return
    setLoadingOlder(true)
    try {
      const page = await listAssignments(spaceId, cursor)
      setItems((current) => {
        const seen = new Set((current ?? []).map((a) => a.id))
        return [...(current ?? []), ...page.items.filter((a) => !seen.has(a.id))]
      })
      setCursor(page.next_cursor)
    } catch {
      setFailed(true)
    } finally {
      setLoadingOlder(false)
    }
  }

  const upsert = useCallback(
    (a: AssignmentDetail) =>
      setItems((current) => {
        const list = current ?? []
        return list.some((i) => i.id === a.id)
          ? list.map((i) => (i.id === a.id ? a : i))
          : [a, ...list]
      }),
    [],
  )

  const removed = useCallback((id: string) => {
    setItems((current) => (current ?? []).filter((a) => a.id !== id))
    setOpenId(null)
  }, [])

  if (openId) {
    return (
      <AssignmentView
        assignmentId={openId}
        subjectId={subjectId}
        isOwner={isOwner}
        canManage={canPost}
        onBack={() => setOpenId(null)}
        onChanged={upsert}
        onDeleted={removed}
      />
    )
  }

  return (
    <div className="space-y-4">
      {isOwner &&
        (!canPost ? (
          <p className="rounded border border-outline-variant bg-surface-variant/40 px-4 py-3 text-body-sm text-on-surface-variant">
            {t('archivedNoPosting')}
          </p>
        ) : creating ? (
          <AssignmentForm
            spaceId={spaceId}
            subjectId={subjectId}
            onSaved={(a) => {
              upsert(a)
              setCreating(false)
            }}
            onCancel={() => setCreating(false)}
          />
        ) : (
          <div className="flex justify-end">
            <button type="button" className={PRIMARY_BUTTON} onClick={() => setCreating(true)}>
              {t('create')}
            </button>
          </div>
        ))}

      {failed && items === null ? (
        <FormBanner>{t('loadFailed')}</FormBanner>
      ) : items === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded border border-dashed border-outline-variant px-4 py-6 text-body-md text-on-surface-variant">
          {t('empty')}
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => setOpenId(a.id)}
                className={`${CARD} block w-full text-start transition-colors hover:bg-surface-container`}
              >
                <span className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="font-headline text-body-lg text-on-surface">{a.title}</span>
                  {a.my_status && <StatusChip status={a.my_status} />}
                  {a.turned_in_count !== null && (
                    <span className="text-body-sm text-on-surface-variant">
                      {t('turnedInCount', { count: a.turned_in_count })}
                    </span>
                  )}
                </span>
                <AssignmentMeta assignment={a} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {failed && items !== null && <FormBanner>{t('loadFailed')}</FormBanner>}

      {cursor && (
        <div className="flex justify-center">
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={loadingOlder}
            onClick={() => void loadOlder()}
          >
            {loadingOlder ? t('loading') : t('loadOlder')}
          </button>
        </div>
      )}
    </div>
  )
}
