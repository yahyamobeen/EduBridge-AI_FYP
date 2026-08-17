'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { DashboardShell } from '@/components/app/DashboardShell'
import { SessionGuard } from '@/components/app/SessionGuard'
import { AuthField } from '@/components/auth/AuthField'
import { FormBanner } from '@/components/ui/FormFeedback'
import {
  CheckCircleIcon,
  GlobeIcon,
  LockIcon,
  ShieldIcon,
  UsersIcon,
} from '@/components/ui/Icon'
import { usePathname, useRouter } from '@/i18n/navigation'
import { routing, toApiLanguage, type Locale } from '@/i18n/routing'
import { changePassword, getEnums, twoFactorStatus, updateMe } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type {
  ApiLanguage,
  EnumsResponse,
  MeResponse,
  TwoFactorStatusResponse,
} from '@/lib/api/types'
import { checkPassword } from '@/lib/auth/passwordRules'

/**
 * FR-A8's screen — the client for all three account-management endpoints.
 *
 * Built from the Stitch prototype, which governs structure, copy and layout
 * while the API contract governs which fields exist. Where the two disagreed
 * the owner decided, and each decision is recorded at the point it applies:
 *
 *   * Board and Class are READ-ONLY. The prototype draws editable dropdowns.
 *   * Student ID is DROPPED. No such field exists anywhere in the schema.
 *   * ONE language control sets the stored preference AND the interface locale.
 *   * Appearance is DROPPED. The application has no dark mode at all.
 *
 * ⚠️ Two prototype conventions are deliberately NOT reproduced. It uses Material
 *    Symbols from a Google CDN, which the CSP forbids (`img-src 'self' data:`)
 *    and which `LoginForm.tsx` already records as not reproduced; icons here are
 *    the existing inline SVGs. And it is written entirely in physical CSS
 *    properties (`ml-`, `pr-`, `text-left`), which `lib/i18n-rules.test.ts`
 *    FAILS THE BUILD on, because Urdu renders right to left.
 */

const CARD =
  'rounded-xl border border-outline-variant bg-surface-container-lowest p-6 shadow-sm'
const CARD_HEADING = 'mb-6 flex items-center gap-2 font-headline text-headline-md text-primary'
const READ_ONLY_FIELD =
  'w-full cursor-not-allowed rounded border border-outline-variant bg-surface-variant/30 px-3 py-2 text-body-md text-on-surface-variant'

export function Settings() {
  return (
    <SessionGuard allow={['student', 'teacher', 'parent', 'admin']}>
      {(me) => <SettingsBody me={me} />}
    </SessionGuard>
  )
}

function SettingsBody({ me }: { me: MeResponse }) {
  const t = useTranslations('settings')
  const router = useRouter()
  const pathname = usePathname()

  return (
    <DashboardShell me={me} subtitle={t('subtitle')}>
      <header className="mb-8">
        <h1 className="font-headline text-headline-lg text-on-background">{t('title')}</h1>
        <p className="text-body-md text-on-surface-variant">{t('subtitle')}</p>
      </header>

      <div className="grid grid-cols-1 gap-gutter lg:grid-cols-3">
        <div className="space-y-gutter lg:col-span-2">
          <ProfileCard me={me} />
          <LanguageCard me={me} router={router} pathname={pathname} />
          <SecurityCard />
        </div>

        <div className="space-y-gutter">
          <ParentalLinkCard me={me} />
        </div>
      </div>
    </DashboardShell>
  )
}

/* -------------------------------------------------------------------------- */

function ProfileCard({ me }: { me: MeResponse }) {
  const t = useTranslations('settings.profile')
  const [fullName, setFullName] = useState(me.full_name ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  // ⚠️ The board LABEL comes from the API, never from a literal list. The
  //    prototype offers "FBISE, Punjab, Sindh, Cambridge"; the `board_code`
  //    enum is PCTB and STBB. Hard-coding either set would be wrong, and
  //    hard-coding the prototype's would be wrong AND untranslated.
  const [boards, setBoards] = useState<EnumsResponse['boards']>([])
  useEffect(() => {
    const controller = new AbortController()
    getEnums(controller.signal)
      .then((enums) => setBoards(enums.boards))
      // A failed reference lookup must not break the screen; the code is shown
      // instead of its label, which is still true and still readable.
      .catch(() => {})
    return () => controller.abort()
  }, [])

  const dirty = fullName.trim() !== (me.full_name ?? '')
  const canSubmit = dirty && fullName.trim() !== '' && !saving

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSaving(true)
    setError(null)
    setFieldErrors({})
    setSaved(false)
    try {
      await updateMe({ full_name: fullName.trim() })
      setSaved(true)
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
        setFieldErrors(caught.fieldErrors())
      } else {
        setError(t('saveFailed'))
      }
    } finally {
      setSaving(false)
    }
  }

  const boardLabel =
    boards.find((b) => b.code === me.profile?.board)?.name ?? me.profile?.board ?? ''

  return (
    <section className={CARD} aria-labelledby="settings-profile">
      <h2 id="settings-profile" className={CARD_HEADING}>
        <UsersIcon className="h-6 w-6" />
        {t('heading')}
      </h2>

      <form onSubmit={save} className="space-y-4" noValidate>
        {error && <FormBanner>{error}</FormBanner>}

        <AuthField
          label={t('fullName')}
          name="full_name"
          type="text"
          autoComplete="name"
          icon={<UsersIcon className="h-5 w-5" />}
          value={fullName}
          onChange={setFullName}
          error={fieldErrors.full_name}
          disabled={saving}
        />

        {/* Students only: the other three roles have no curriculum context. */}
        {me.profile !== null && (
          <>
            <ReadOnlyField label={t('board')} value={boardLabel} />
            <ReadOnlyField label={t('classLevel')} value={String(me.profile.class_level)} />
            <p className="text-body-sm text-on-surface-variant">{t('contextLocked')}</p>
          </>
        )}

        <SaveRow
          canSubmit={canSubmit}
          saving={saving}
          saved={saved}
          onCancel={() => {
            setFullName(me.full_name ?? '')
            setSaved(false)
            setError(null)
          }}
        />
      </form>
    </section>
  )
}

/**
 * ⚠️ Board and Class are rendered, not edited — finding B4.
 *
 * `class_level` is the input the parental-consent gate reads, so a Class 9
 * student choosing 11 would leave the gate permanently; `board` scopes every
 * progress record ever written for them. `20260816160000` revoked the column
 * grants, so the API refuses these regardless of what this screen sends — this
 * is the honest presentation of a decision the database enforces.
 */
function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <label className="mb-1 block text-body-sm font-medium text-on-surface">{label}</label>
      <p className={READ_ONLY_FIELD}>{value}</p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

const LANGUAGE_OPTIONS: readonly Locale[] = routing.locales

function LanguageCard({
  me,
  router,
  pathname,
}: {
  me: MeResponse
  router: ReturnType<typeof useRouter>
  pathname: string
}) {
  const t = useTranslations('settings.language')
  const [pending, setPending] = useState<Locale | null>(null)
  const [error, setError] = useState<string | null>(null)

  // ⚠️ FROM THE TOP LEVEL, NOT FROM `profile`. Reading `me.profile?.language_pref`
  //    here silently showed English to every teacher, parent and administrator,
  //    because `profile` is `null` for them — while `PATCH /auth/me` was happily
  //    accepting their choice. The column has been on `app_user` since
  //    20260816200000; this is the read side catching up.
  const stored: ApiLanguage = me.language_pref

  /**
   * ⚠️ THIS CONTROL DOES TWO UNRELATED THINGS, and missing the second is the
   * easy mistake. The STORED preference is an API write (`PATCH /auth/me`,
   * values `en | ur | roman_ur`) and governs outgoing email. The INTERFACE
   * locale is a ROUTE CHANGE, because the locale is a URL segment.
   *
   * The API write happens first: if it fails there is nothing to undo, whereas
   * navigating first would leave the user on a page in a language the server
   * does not think they chose.
   *
   * ⚠️ The two value sets are NOT the same strings — `ur-Latn` on the web is
   * `roman_ur` in the API — so they are mapped through `toApiLanguage` rather
   * than passed straight across.
   */
  async function choose(locale: Locale) {
    if (pending !== null) return
    setPending(locale)
    setError(null)
    try {
      await updateMe({ language_pref: toApiLanguage(locale) })
      router.replace(pathname, { locale })
    } catch {
      setError(t('saveFailed'))
      setPending(null)
    }
  }

  return (
    <section className={CARD} aria-labelledby="settings-language">
      <h2 id="settings-language" className={CARD_HEADING}>
        <GlobeIcon className="h-6 w-6" />
        {t('heading')}
      </h2>

      {error && <FormBanner>{error}</FormBanner>}

      <fieldset className="space-y-3">
        <legend className="mb-3 text-body-md text-on-surface-variant">{t('legend')}</legend>
        {LANGUAGE_OPTIONS.map((locale) => {
          const selected = toApiLanguage(locale) === stored
          return (
            <label
              key={locale}
              className={`flex cursor-pointer items-center gap-3 rounded-md border p-4 transition-colors ${
                selected
                  ? 'border-primary bg-primary-fixed/40'
                  : 'border-outline-variant hover:bg-surface-container'
              }`}
            >
              <input
                type="radio"
                name="language"
                value={locale}
                checked={selected}
                disabled={pending !== null}
                onChange={() => void choose(locale)}
                className="h-4 w-4 accent-primary"
              />
              <span className="flex-1 text-body-md text-on-surface">
                {t(`option_${locale}`)}
              </span>
              {selected && <CheckCircleIcon className="h-5 w-5 text-status-verified" />}
            </label>
          )
        })}
      </fieldset>

      <p className="mt-4 text-body-sm text-on-surface-variant">{t('note')}</p>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function SecurityCard() {
  const t = useTranslations('settings.security')
  const tp = useTranslations('auth.password')
  const te = useTranslations('auth.errors')

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [twoFactor, setTwoFactor] = useState<TwoFactorStatusResponse | null>(null)
  useEffect(() => {
    twoFactorStatus()
      .then(setTwoFactor)
      .catch(() => {})
  }, [])

  const checks = checkPassword(next)
  const mismatch = confirm !== '' && confirm !== next
  const canSubmit =
    !submitting &&
    current !== '' &&
    checks.every((c) => !c.gates || c.met) &&
    confirm === next &&
    confirm !== ''

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      await changePassword({ current_password: current, new_password: next })
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (caught) {
      // ⚠️ A WRONG CURRENT PASSWORD IS `401 UNAUTHENTICATED`, which is also what
      //    an expired session looks like. The contract forbids a bespoke code
      //    (tdd.md §7.3), so the two are indistinguishable here — and the
      //    client wrapper passes `noRetry` precisely so a mistyped password
      //    does not fire a token refresh. Branching on `code`, never `message`.
      if (caught instanceof ApiError && caught.code === 'UNAUTHENTICATED') {
        setError(t('wrongPassword'))
      } else if (caught instanceof ApiError && caught.code === 'RATE_LIMITED') {
        setError(te('rateLimited'))
      } else if (caught instanceof ApiError && caught.code === 'VALIDATION_ERROR') {
        setError(te('generic'))
      } else {
        setError(te('generic'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className={CARD} aria-labelledby="settings-security">
      <h2 id="settings-security" className={CARD_HEADING}>
        <ShieldIcon className="h-6 w-6" />
        {t('heading')}
      </h2>

      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <FormBanner>{error}</FormBanner>}
        {done && (
          <p className="flex items-center gap-2 rounded border border-status-verified/40 bg-secondary-container/40 p-3 text-body-sm text-on-secondary-container">
            <CheckCircleIcon className="h-5 w-5 shrink-0" />
            {t('changed')}
          </p>
        )}

        <AuthField
          label={t('currentPassword')}
          name="current_password"
          type="password"
          autoComplete="current-password"
          icon={<LockIcon className="h-5 w-5" />}
          value={current}
          onChange={setCurrent}
          disabled={submitting}
          required
        />
        <AuthField
          label={t('newPassword')}
          name="new_password"
          type="password"
          autoComplete="new-password"
          icon={<LockIcon className="h-5 w-5" />}
          value={next}
          onChange={setNext}
          disabled={submitting}
          required
        />

        <ul className="space-y-2 rounded border border-outline-variant/50 bg-surface-container-highest p-3">
          <li className="mb-1 text-label-caps uppercase text-outline">{tp('rulesTitle')}</li>
          {checks.map((check) => (
            <li
              key={check.key}
              className={`flex items-center gap-2 text-body-sm ${
                check.met ? 'text-on-surface' : 'text-on-surface-variant'
              }`}
            >
              {/* Met-ness carried by icon and weight, not colour alone (A11Y-1a). */}
              {check.met ? (
                <CheckCircleIcon className="h-4 w-4 shrink-0 text-status-verified" />
              ) : (
                <span
                  aria-hidden="true"
                  className="h-4 w-4 shrink-0 rounded-full border border-outline"
                />
              )}
              <span>{tp(`rule_${check.key}`)}</span>
              <span className="sr-only">{check.met ? tp('ruleMet') : tp('ruleNotMet')}</span>
            </li>
          ))}
        </ul>

        <AuthField
          label={t('confirmPassword')}
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          icon={<LockIcon className="h-5 w-5" />}
          value={confirm}
          onChange={setConfirm}
          error={mismatch ? tp('mismatch') : undefined}
          disabled={submitting}
          required
        />

        <p className="text-body-sm text-on-surface-variant">{t('signsYouOut')}</p>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t('changing') : t('changePassword')}
          </button>
        </div>
      </form>

      {/*
        READ-ONLY, and deliberately so. Enrolment, disabling and regenerating
        backup codes are out of scope, and `POST /api/auth/2fa/backup-codes`
        does not exist — the count is shown here precisely so it can be read
        WITHOUT the endpoint that replaces every code (user-stories.md:93).
      */}
      <div className="mt-6 border-t border-outline-variant pt-6">
        <h3 className="mb-2 font-headline text-body-lg text-on-surface">
          {t('twoFactorHeading')}
        </h3>
        {twoFactor === null ? (
          <p className="text-body-sm text-on-surface-variant">{t('twoFactorLoading')}</p>
        ) : twoFactor.enabled ? (
          <dl className="space-y-1 text-body-sm">
            <div className="flex gap-2">
              <dt className="text-on-surface-variant">{t('twoFactorMethod')}</dt>
              <dd className="text-on-surface">{t(`method_${twoFactor.method}`)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-on-surface-variant">{t('backupCodes')}</dt>
              <dd className="text-on-surface">{twoFactor.backup_codes_remaining}</dd>
            </div>
          </dl>
        ) : (
          <p className="text-body-sm text-on-surface-variant">{t('twoFactorDisabled')}</p>
        )}
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function ParentalLinkCard({ me }: { me: MeResponse }) {
  const t = useTranslations('settings.guardian')

  // Only Class 9-10 students have a gate at all (prd.md §4.3). For everyone
  // else the card would state a rule that does not apply to them.
  if (!me.guardian.required) return null

  const status = me.guardian.status
  return (
    <section className={CARD} aria-labelledby="settings-guardian">
      <h2
        id="settings-guardian"
        className="font-label-caps mb-4 text-label-caps uppercase text-on-surface-variant"
      >
        {t('heading')}
      </h2>
      <p className="mb-3 flex items-center gap-2 text-body-md text-on-surface">
        <ShieldIcon className="h-5 w-5 text-primary" />
        {status === null ? t('status_none') : t(`status_${status}`)}
      </p>
      <p className="text-body-sm text-on-surface-variant">{t('readOnly')}</p>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function SaveRow({
  canSubmit,
  saving,
  saved,
  onCancel,
}: {
  canSubmit: boolean
  saving: boolean
  saved: boolean
  onCancel: () => void
}) {
  const t = useTranslations('settings')
  return (
    <div className="flex items-center justify-end gap-3">
      {saved && (
        <span className="flex items-center gap-1 text-body-sm text-status-verified">
          <CheckCircleIcon className="h-4 w-4" />
          {t('saved')}
        </span>
      )}
      <button
        type="button"
        onClick={onCancel}
        disabled={!canSubmit}
        className="rounded border border-outline px-6 py-3 text-label-caps uppercase text-on-surface transition-colors hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t('cancel')}
      </button>
      <button
        type="submit"
        disabled={!canSubmit}
        className="rounded bg-primary px-6 py-3 text-label-caps uppercase text-on-primary shadow-sm transition-colors hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? t('saving') : t('save')}
      </button>
    </div>
  )
}
