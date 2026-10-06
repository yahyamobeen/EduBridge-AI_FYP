'use client'

import { useCallback, useEffect, useState } from 'react'
import { useFormatter, useTranslations } from 'next-intl'
import { RequireRole } from '@/components/app/SessionGuard'
import { FormBanner } from '@/components/ui/FormFeedback'
import { ArrowLeftIcon, CheckCircleIcon, KeyIcon, UsersIcon } from '@/components/ui/Icon'
import { tabId, tabPanelId, Tabs } from '@/components/ui/Tabs'
import { Link, useRouter } from '@/i18n/navigation'
import {
  changeJoinCode,
  getPeople,
  getSpace,
  leaveSpace,
  removeMember,
  setMemberMuted,
  updateSpace,
} from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { PeopleResponse, SpaceDetail } from '@/lib/api/types'
import { ChatTab } from './ChatTab'
import { ClassworkTab } from './ClassworkTab'
import { ConfirmInline } from './ConfirmInline'
import { StreamTab } from './StreamTab'
import {
  CARD,
  CARD_HEADING,
  DANGER_BUTTON,
  FIELD,
  LABEL,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  UUID_RE,
} from './styles'

/** Stream first: it is what changes. */
const TABS = ['stream', 'classwork', 'chat', 'people'] as const
type ClassroomTab = (typeof TABS)[number]

/**
 * One classroom — `/classroom/[spaceId]` (student) and
 * `/teacher/classroom/[spaceId]` (teacher).
 *
 * ⚠️ OWNER CONTROLS RENDER FROM THE SERVER'S ANSWER, NOT FROM THE ROLE. The join
 *    code, rename, archive and remove controls appear only when GET /spaces/{id}
 *    says `viewer_role === 'owner'` AND `can_manage`. A teacher looking at a
 *    classroom whose subject scope was revoked is still `owner` but gets no
 *    controls, and is told why. None of this is the security boundary — the
 *    database is (database.md invariant 9) — but prd.md §4.2 also forbids
 *    rendering a control the caller cannot use, even disabled.
 */
type ClassroomRouteProps = {
  spaceId: string
  /** From `?assignment=` — opens Classwork on that assignment. Ignored unless a UUID. */
  assignmentId?: string
}

export function StudentClassroom({ spaceId, assignmentId }: ClassroomRouteProps) {
  return (
    <RequireRole allow={['student']}>
      {() => (
        <ClassroomView spaceId={spaceId} listPath="/classroom" assignmentId={assignmentId} />
      )}
    </RequireRole>
  )
}

export function TeacherClassroom({ spaceId, assignmentId }: ClassroomRouteProps) {
  return (
    <RequireRole allow={['teacher']}>
      {() => (
        <ClassroomView
          spaceId={spaceId}
          listPath="/teacher/classroom"
          assignmentId={assignmentId}
        />
      )}
    </RequireRole>
  )
}

export function ClassroomView({
  spaceId,
  listPath,
  assignmentId,
}: {
  spaceId: string
  listPath: string
  assignmentId?: string
}) {
  const t = useTranslations('classroom')
  const validId = UUID_RE.test(spaceId)
  const [space, setSpace] = useState<SpaceDetail | null>(null)
  const [failed, setFailed] = useState(!validId)

  useEffect(() => {
    if (!validId) return
    const controller = new AbortController()
    getSpace(spaceId, controller.signal)
      .then(setSpace)
      .catch((e) => {
        // A 403 is "unknown or not yours" — the server answers both the same
        // way, deliberately, and so does this screen.
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
      })
    return () => controller.abort()
  }, [spaceId, validId])

  const openAssignment = assignmentId && UUID_RE.test(assignmentId) ? assignmentId : undefined
  const [tab, setTab] = useState<ClassroomTab>(openAssignment ? 'classwork' : 'stream')
  const isOwner = space?.viewer_role === 'owner' && space.can_manage

  return (
    <>
      <Link
        href={listPath}
        className="mb-6 inline-flex items-center gap-2 text-body-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeftIcon className="h-4 w-4 rtl:-scale-x-100" />
        {t('detail.back')}
      </Link>

      {failed ? (
        <FormBanner>{t('detail.unavailable')}</FormBanner>
      ) : space === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : (
        <>
          <header className="mb-6">
            <h1 className="font-headline text-headline-lg text-on-background">{space.title}</h1>
            <p className="text-body-md text-on-surface-variant">
              {t('card.subjectLine', {
                subject: space.subject.name,
                classLevel: space.subject.class_level,
                board: space.subject.board,
              })}
            </p>
            {space.viewer_role === 'member' && (
              <p className="text-body-sm text-on-surface-variant">
                {t('card.teacher', { name: space.owner_name ?? t('card.unnamedTeacher') })}
              </p>
            )}
          </header>

          {space.status === 'archived' && (
            <p className="mb-6 rounded border border-outline-variant bg-surface-variant/40 px-4 py-3 text-body-sm text-on-surface-variant">
              {t('detail.archivedNotice')}
            </p>
          )}
          {space.viewer_role === 'owner' && !space.can_manage && (
            <div className="mb-6">
              <FormBanner>{t('detail.revokedNotice')}</FormBanner>
            </div>
          )}

          <div className="grid grid-cols-1 gap-gutter lg:grid-cols-3">
            <div className="lg:col-span-2">
              {(space.viewer_role === 'member' || isOwner) && (
                <>
                  <Tabs
                    label={t('tabs.label')}
                    value={tab}
                    onChange={setTab}
                    items={TABS.map((key) => ({ key, label: t(`tabs.${key}`) }))}
                  />
                  <div role="tabpanel" id={tabPanelId(tab)} aria-labelledby={tabId(tab)}>
                    {tab === 'stream' ? (
                      <StreamTab
                        spaceId={space.id}
                        isOwner={isOwner}
                        canPost={isOwner && space.status === 'active'}
                        authorName={space.owner_name ?? t('card.unnamedTeacher')}
                      />
                    ) : tab === 'classwork' ? (
                      <ClassworkTab
                        spaceId={space.id}
                        subjectId={space.subject.id}
                        isOwner={isOwner}
                        canPost={isOwner && space.status === 'active'}
                        initialOpenId={openAssignment}
                      />
                    ) : tab === 'chat' ? (
                      <ChatTab
                        key={space.id}
                        spaceId={space.id}
                        isOwner={isOwner}
                        archived={space.status === 'archived'}
                        onSpaceChange={setSpace}
                      />
                    ) : (
                      <PeopleSection
                        spaceId={space.id}
                        isOwner={isOwner}
                        onMemberRemoved={() =>
                          setSpace((s) =>
                            s && s.member_count !== null
                              ? { ...s, member_count: Math.max(0, s.member_count - 1) }
                              : s,
                          )
                        }
                      />
                    )}
                  </div>
                </>
              )}
            </div>
            <div className="space-y-gutter">
              {isOwner && <JoinCodePanel space={space} onChange={setSpace} />}
              {isOwner && <ManagePanel space={space} onChange={setSpace} />}
              {space.viewer_role === 'member' && (
                <LeavePanel space={space} listPath={listPath} />
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}

/* -------------------------------------------------------------------------- */

function PeopleSection({
  spaceId,
  isOwner,
  onMemberRemoved,
}: {
  spaceId: string
  isOwner: boolean
  onMemberRemoved: () => void
}) {
  const t = useTranslations('classroom.people')
  const format = useFormatter()
  const [people, setPeople] = useState<PeopleResponse | null>(null)
  const [failed, setFailed] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [removeFailed, setRemoveFailed] = useState(false)
  const [muting, setMuting] = useState<string | null>(null)
  const [muteFailed, setMuteFailed] = useState(false)

  const load = useCallback(
    (signal?: AbortSignal) =>
      getPeople(spaceId, signal)
        .then(setPeople)
        .catch((e) => {
          if (!(e instanceof DOMException && e.name === 'AbortError')) setFailed(true)
        }),
    [spaceId],
  )

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  async function remove(studentId: string) {
    setBusy(true)
    setRemoveFailed(false)
    try {
      await removeMember(spaceId, studentId)
      setConfirming(null)
      setPeople((p) =>
        p ? { ...p, members: p.members.filter((m) => m.user_id !== studentId) } : p,
      )
      onMemberRemoved()
    } catch {
      setRemoveFailed(true)
    } finally {
      setBusy(false)
    }
  }

  async function toggleMute(studentId: string, muted: boolean) {
    setMuting(studentId)
    setMuteFailed(false)
    try {
      await setMemberMuted(spaceId, studentId, muted)
      setPeople((p) =>
        p
          ? {
              ...p,
              members: p.members.map((m) => (m.user_id === studentId ? { ...m, muted } : m)),
            }
          : p,
      )
    } catch {
      setMuteFailed(true)
    } finally {
      setMuting(null)
    }
  }

  return (
    <section aria-labelledby="people-heading" className={CARD}>
      <h2 id="people-heading" className={CARD_HEADING}>
        <UsersIcon className="h-5 w-5" />
        {t('heading')}
      </h2>

      {failed ? (
        <FormBanner>{t('unavailable')}</FormBanner>
      ) : people === null ? (
        <p role="status" className="text-body-md text-on-surface-variant">
          {t('loading')}
        </p>
      ) : (
        <>
          <h3 className="mb-2 text-label-caps uppercase text-on-surface-variant">
            {t('teacher')}
          </h3>
          <p className="mb-6 text-body-md text-on-surface">
            {people.owner.full_name ?? t('unnamed')}
          </p>

          <h3 className="mb-2 text-label-caps uppercase text-on-surface-variant">
            {t('students', { count: people.members.length })}
          </h3>
          {people.members.length === 0 ? (
            <p className="text-body-md text-on-surface-variant">{t('empty')}</p>
          ) : (
            <ul className="divide-y divide-outline-variant">
              {people.members.map((m) => {
                const name = m.full_name ?? t('unnamed')
                return (
                  <li key={m.user_id} className="py-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-body-md text-on-surface">{name}</p>
                        <p className="text-body-sm text-on-surface-variant">
                          {t('joined', {
                            date: format.dateTime(new Date(m.joined_at), {
                              dateStyle: 'medium',
                            }),
                          })}
                        </p>
                        {m.muted && (
                          <p className="text-body-sm font-semibold text-on-surface-variant">
                            {t('muted')}
                          </p>
                        )}
                      </div>
                      {isOwner && confirming !== m.user_id && (
                        <div className="flex flex-wrap gap-3">
                          <button
                            type="button"
                            className={SECONDARY_BUTTON}
                            disabled={muting === m.user_id}
                            onClick={() => void toggleMute(m.user_id, !m.muted)}
                          >
                            {m.muted ? t('unmute') : t('mute')}
                          </button>
                          <button
                            type="button"
                            className={SECONDARY_BUTTON}
                            onClick={() => setConfirming(m.user_id)}
                          >
                            {t('remove')}
                          </button>
                        </div>
                      )}
                    </div>
                    {isOwner && confirming === m.user_id && (
                      <ConfirmInline
                        question={t('removeConfirm', { name })}
                        confirmLabel={t('remove')}
                        busy={busy}
                        onConfirm={() => void remove(m.user_id)}
                        onCancel={() => setConfirming(null)}
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {removeFailed && (
            <div className="mt-4">
              <FormBanner>{t('removeFailed')}</FormBanner>
            </div>
          )}
          {muteFailed && (
            <div className="mt-4">
              <FormBanner>{t('muteFailed')}</FormBanner>
            </div>
          )}
        </>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function JoinCodePanel({
  space,
  onChange,
}: {
  space: SpaceDetail
  onChange: (s: SpaceDetail) => void
}) {
  const t = useTranslations('classroom.code')
  const [confirming, setConfirming] = useState<'rotate' | 'disable' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')
  const archived = space.status === 'archived'

  async function act(action: 'rotate' | 'disable') {
    setBusy(true)
    setError(false)
    try {
      const { join_code } = await changeJoinCode(space.id, action)
      onChange({ ...space, join_code })
      setConfirming(null)
      setCopied('idle')
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!space.join_code) return
    try {
      await navigator.clipboard.writeText(space.join_code)
      setCopied('done')
    } catch {
      // The code is still on screen and selectable: the failure is visible,
      // not silent (the BackupCodes.tsx rule).
      setCopied('failed')
    }
  }

  return (
    <section aria-labelledby="code-heading" className={CARD}>
      <h2 id="code-heading" className={CARD_HEADING}>
        <KeyIcon className="h-5 w-5" />
        {t('heading')}
      </h2>

      {space.join_code ? (
        <>
          <p
            className="force-ltr mb-2 rounded bg-surface-container-high px-4 py-3 text-center font-mono text-headline-md tracking-[0.3em] text-on-surface"
            aria-label={t('codeLabel')}
          >
            {space.join_code}
          </p>
          <p className="mb-4 text-body-sm text-on-surface-variant">{t('hint')}</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" className={PRIMARY_BUTTON} onClick={() => void copy()}>
              {t('copy')}
            </button>
            {!archived && (
              <button
                type="button"
                className={SECONDARY_BUTTON}
                onClick={() => setConfirming('rotate')}
              >
                {t('rotate')}
              </button>
            )}
            <button
              type="button"
              className={SECONDARY_BUTTON}
              onClick={() => setConfirming('disable')}
            >
              {t('disable')}
            </button>
          </div>
          {copied === 'done' && (
            <p
              role="status"
              className="mt-3 flex items-center gap-1 text-body-sm text-status-verified"
            >
              <CheckCircleIcon className="h-4 w-4" />
              {t('copied')}
            </p>
          )}
          {copied === 'failed' && (
            <p role="status" className="mt-3 text-body-sm text-on-surface-variant">
              {t('copyFailed')}
            </p>
          )}
        </>
      ) : (
        <>
          <p className="mb-4 text-body-md text-on-surface-variant">
            {archived ? t('archivedOff') : t('off')}
          </p>
          {!archived && (
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={busy}
              onClick={() => void act('rotate')}
            >
              {t('enable')}
            </button>
          )}
        </>
      )}

      {confirming && (
        <ConfirmInline
          question={confirming === 'rotate' ? t('rotateConfirm') : t('disableConfirm')}
          confirmLabel={confirming === 'rotate' ? t('rotate') : t('disable')}
          busy={busy}
          onConfirm={() => void act(confirming)}
          onCancel={() => setConfirming(null)}
        />
      )}
      {error && (
        <div className="mt-4">
          <FormBanner>{t('failed')}</FormBanner>
        </div>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function ManagePanel({
  space,
  onChange,
}: {
  space: SpaceDetail
  onChange: (s: SpaceDetail) => void
}) {
  const t = useTranslations('classroom.manage')
  const [title, setTitle] = useState(space.title)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = title.trim() !== '' && title.trim() !== space.title
  const archived = space.status === 'archived'

  async function save(patch: { title?: string; status?: 'active' | 'archived' }) {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await updateSpace(space.id, patch)
      onChange(updated)
      setTitle(updated.title)
      setConfirmArchive(false)
      setSaved(true)
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.details.reason === 'classroom_limit'
          ? t('limit')
          : t('failed'),
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby="manage-heading" className={CARD}>
      <h2 id="manage-heading" className={CARD_HEADING}>
        {t('heading')}
      </h2>

      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (dirty && !saving) void save({ title: title.trim() })
        }}
      >
        <label htmlFor="manage-title" className={LABEL}>
          {t('titleLabel')}
        </label>
        <input
          id="manage-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={120}
          className={FIELD}
        />
        <div className="mt-3 flex items-center justify-end gap-3">
          {saved && (
            <span
              role="status"
              className="flex items-center gap-1 text-body-sm text-status-verified"
            >
              <CheckCircleIcon className="h-4 w-4" />
              {t('saved')}
            </span>
          )}
          <button type="submit" disabled={!dirty || saving} className={PRIMARY_BUTTON}>
            {saving ? t('saving') : t('save')}
          </button>
        </div>
      </form>

      <div className="mt-6 border-t border-outline-variant pt-6">
        <p className="mb-3 text-body-sm text-on-surface-variant">
          {archived ? t('unarchiveHint') : t('archiveHint')}
        </p>
        {archived ? (
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={saving}
            onClick={() => void save({ status: 'active' })}
          >
            {t('unarchive')}
          </button>
        ) : (
          !confirmArchive && (
            <button
              type="button"
              className={DANGER_BUTTON}
              onClick={() => setConfirmArchive(true)}
            >
              {t('archive')}
            </button>
          )
        )}
        {confirmArchive && (
          <ConfirmInline
            question={t('archiveConfirm')}
            confirmLabel={t('archive')}
            busy={saving}
            onConfirm={() => void save({ status: 'archived' })}
            onCancel={() => setConfirmArchive(false)}
          />
        )}
      </div>

      {error && (
        <div className="mt-4">
          <FormBanner>{error}</FormBanner>
        </div>
      )}
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function LeavePanel({ space, listPath }: { space: SpaceDetail; listPath: string }) {
  const t = useTranslations('classroom.leave')
  const router = useRouter()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function leave() {
    setBusy(true)
    setFailed(false)
    try {
      await leaveSpace(space.id)
      router.push(listPath)
    } catch {
      // Navigates away on success, so re-enabled only on failure.
      setBusy(false)
      setFailed(true)
    }
  }

  return (
    <section aria-labelledby="leave-heading" className={CARD}>
      <h2 id="leave-heading" className={CARD_HEADING}>
        {t('heading')}
      </h2>
      <p className="mb-4 text-body-sm text-on-surface-variant">{t('body')}</p>
      {!confirming && (
        <button type="button" className={DANGER_BUTTON} onClick={() => setConfirming(true)}>
          {t('button')}
        </button>
      )}
      {confirming && (
        <ConfirmInline
          question={t('confirm', { title: space.title })}
          confirmLabel={t('button')}
          busy={busy}
          onConfirm={() => void leave()}
          onCancel={() => setConfirming(false)}
        />
      )}
      {failed && (
        <div className="mt-4">
          <FormBanner>{t('failed')}</FormBanner>
        </div>
      )}
    </section>
  )
}
