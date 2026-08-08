'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { register as registerAccount } from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/errors'
import type { BoardCode, EnumsResponse, Medium, StudentGroup } from '@/lib/api/types'
import { toApiLanguage, type Locale } from '@/i18n/routing'
import { useRouter } from '@/i18n/navigation'
import { FormBanner } from '@/components/ui/FormFeedback'
import { RadioCards, TextField, type Option } from './fields'

const STEPS = ['step1', 'step2', 'step3'] as const

type Draft = {
  full_name: string
  email: string
  password: string
  confirm_password: string
  board: string
  class_level: string
  student_group: string
  medium: string
  language_pref: string
}

/**
 * Three-step student registration, following the prototype's structure:
 * a branded sidebar carrying numbered step indicators, and the form beside it.
 *
 * The prototype's academic step is missing two fields the contract requires --
 * elective group and interface language -- and its third step is an alert()
 * stub. Both are built here.
 */
export function StudentSignupForm({ enums }: { enums: EnumsResponse }) {
  const t = useTranslations('signup.student')
  const tc = useTranslations('signup.common')
  const te = useTranslations('signup.errors')
  const locale = useLocale() as Locale
  const router = useRouter()

  const [step, setStep] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<Draft>({
    full_name: '',
    email: '',
    password: '',
    confirm_password: '',
    board: '',
    class_level: '',
    student_group: '',
    medium: '',
    language_pref: toApiLanguage(locale),
  })

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  /**
   * Options for the chosen class. `groups_by_class` is keyed by STRING while
   * `class_levels` are NUMBERS, so the key is normalised rather than passed
   * through — comparisons between the two never coerce.
   */
  const groupOptions: Option[] = draft.class_level
    ? (enums.groups_by_class[String(draft.class_level)] ?? []).map((g) => ({
        value: g.code,
        label: g.label,
      }))
    : []

  /**
   * Changing the class CLEARS the group. Without this a student picks Class 9
   * and `science`, switches to Class 11, and `science` silently survives into
   * an invalid pair that only the server would catch.
   */
  const onClassChange = (next: string) => {
    setDraft((d) => ({ ...d, class_level: next, student_group: '' }))
    setFieldErrors((e) => ({ ...e, student_group: '' }))
  }

  const mismatch = draft.confirm_password !== '' && draft.confirm_password !== draft.password
  const basicComplete =
    draft.full_name.trim() !== '' &&
    draft.email.trim() !== '' &&
    draft.password.length >= 8 &&
    draft.confirm_password === draft.password &&
    draft.confirm_password !== ''
  // Submit stays unreachable until the pair is valid, so 422 INVALID_CLASS_GROUP
  // cannot be produced through the UI. It is still handled if it ever arrives.
  const academicComplete =
    draft.board !== '' &&
    draft.class_level !== '' &&
    draft.student_group !== '' &&
    draft.medium !== ''

  const needsGuardian = draft.class_level === '9' || draft.class_level === '10'

  async function submit() {
    setSubmitting(true)
    setFormError(null)
    setFieldErrors({})
    try {
      await registerAccount({
        email: draft.email,
        password: draft.password,
        full_name: draft.full_name,
        role: 'student',
        board: draft.board as BoardCode,
        // The contract types class_level as a number; the radio value is a string.
        class_level: Number(draft.class_level),
        student_group: draft.student_group as StudentGroup,
        medium: draft.medium as Medium,
        language_pref: draft.language_pref as Draft['language_pref'] & 'en',
      })
      // Registration issues no session: the account starts at
      // email_verification_pending (tdd.md §3.1).
      router.push('/onboarding/email')
    } catch (error) {
      if (!(error instanceof ApiError)) {
        setFormError(te('generic'))
      } else if (error.code === 'EMAIL_ALREADY_REGISTERED') {
        setFieldErrors({ email: te('emailTaken') })
        setStep(0)
      } else if (error.code === 'VALIDATION_ERROR') {
        setFieldErrors(error.fieldErrors())
        setStep(0)
      } else if (error.code === 'INVALID_CLASS_GROUP') {
        setFormError(te('invalidClassGroup'))
        setStep(1)
      } else if (error.code === 'RATE_LIMITED') {
        setFormError(te('rateLimited'))
      } else {
        setFormError(te('generic'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  const boardOptions: Option[] = enums.boards.map((b) => ({
    value: b.code,
    label: b.code,
    sublabel: b.code === 'PCTB' ? t('boardPCTB') : t('boardSTBB'),
  }))

  return (
    <div className="flex min-h-[calc(100vh-4rem)] w-full flex-col md:flex-row">
      {/* Branded sidebar with step indicators, as in the prototype. */}
      <aside className="relative hidden w-2/5 flex-col overflow-hidden bg-primary-container p-12 text-on-primary-container md:flex">
        <p className="font-headline text-headline-lg font-bold">EduBridge AI</p>
        <p className="mt-2 max-w-md text-body-lg opacity-90">{t('subtitle')}</p>

        <ol className="mt-auto space-y-6">
          {STEPS.map((key, index) => (
            <li
              key={key}
              className={`flex items-center gap-3 transition-opacity duration-300 ${
                index === step ? 'opacity-100' : 'opacity-50'
              }`}
              aria-current={index === step ? 'step' : undefined}
            >
              <span
                className={`flex h-8 w-8 items-center justify-center rounded-full font-bold ${
                  index === step
                    ? 'bg-on-primary-container text-primary-container'
                    : 'border-2 border-on-primary-container'
                }`}
              >
                {index + 1}
              </span>
              <span className="font-headline text-body-md">{t(key)}</span>
            </li>
          ))}
        </ol>
      </aside>

      <div className="flex flex-1 items-center justify-center bg-surface px-gutter py-12">
        <div className="w-full max-w-xl">
          <p className="text-label-caps uppercase text-on-surface-variant md:hidden">
            {tc('stepOf', { current: step + 1, total: STEPS.length })}
          </p>

          {/* Steps swap with the prototype's fade-and-rise. */}
          <div key={step} className="motion-safe:animate-roll-down">
            {step === 0 && (
              <section aria-labelledby="s1">
                <h1 id="s1" className="font-headline text-headline-lg text-on-primary-fixed">
                  {t('title')}
                </h1>
                <p className="mt-2 text-body-md text-on-surface-variant">{t('subtitle')}</p>

                <div className="mt-8 space-y-5">
                  {formError && <FormBanner>{formError}</FormBanner>}
                  <TextField
                    label={tc('fullName')}
                    name="full_name"
                    autoComplete="name"
                    required
                    error={fieldErrors.full_name}
                    register={{
                      value: draft.full_name,
                      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                        set('full_name', e.target.value),
                    }}
                  />
                  <TextField
                    label={tc('email')}
                    name="email"
                    type="email"
                    autoComplete="username"
                    required
                    error={fieldErrors.email}
                    register={{
                      value: draft.email,
                      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                        set('email', e.target.value),
                    }}
                  />
                  <TextField
                    label={tc('password')}
                    name="password"
                    type="password"
                    autoComplete="new-password"
                    hint={tc('passwordHint')}
                    required
                    error={fieldErrors.password}
                    register={{
                      value: draft.password,
                      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                        set('password', e.target.value),
}}
                    />
                  <TextField
                    label={tc('confirmPassword')}
                    name="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    hint={tc('confirmPasswordHint')}
                    required
                    error={mismatch ? tc('mismatch') : fieldErrors.confirm_password}
                    register={{
                      value: draft.confirm_password,
                      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
                        set('confirm_password', e.target.value),
                    }}
                  />
                </div>
              </section>
            )}

            {step === 1 && (
              <section aria-labelledby="s2">
                <h1 id="s2" className="font-headline text-headline-lg text-on-primary-fixed">
                  {t('step2')}
                </h1>
                <p className="mt-2 text-body-md text-on-surface-variant">
                  {t('academicIntro')}
                </p>

                <div className="mt-8 space-y-6">
                  {formError && <FormBanner>{formError}</FormBanner>}

                  <RadioCards
                    legend={t('board')}
                    name="board"
                    options={boardOptions}
                    value={draft.board}
                    onChange={(v) => set('board', v)}
                  />

                  <RadioCards
                    legend={t('classLevel')}
                    name="class_level"
                    columns={4}
                    compact
                    options={enums.class_levels.map((level) => ({
                      value: String(level),
                      label: t('classOption', { level }),
                    }))}
                    value={draft.class_level}
                    onChange={onClassChange}
                  />

                  <RadioCards
                    legend={t('group')}
                    name="student_group"
                    columns={3}
                    options={groupOptions}
                    value={draft.student_group}
                    onChange={(v) => set('student_group', v)}
                    hint={t('groupHelp')}
                    disabledMessage={t('groupPickClassFirst')}
                  />

                  {needsGuardian && (
                    <div className="rounded-e border-s-4 border-status-pending bg-surface-container-high p-4">
                      <p className="font-headline text-body-md font-semibold">
                        {t('consentTitle')}
                      </p>
                      <p className="mt-1 text-body-sm text-on-surface-variant">
                        {t('consentBody')}
                      </p>
                    </div>
                  )}

                  <RadioCards
                    legend={t('medium')}
                    name="medium"
                    options={enums.mediums.map((m) => ({
                      value: m,
                      label: m === 'en' ? t('mediumEn') : t('mediumUr'),
                    }))}
                    value={draft.medium}
                    onChange={(v) => set('medium', v)}
                  />

                  <RadioCards
                    legend={t('language')}
                    name="language_pref"
                    columns={3}
                    options={enums.languages.map((l) => ({
                      value: l,
                      label: l === 'en' ? 'English' : l === 'ur' ? 'اردو' : 'Roman Urdu',
                    }))}
                    value={draft.language_pref}
                    onChange={(v) => set('language_pref', v)}
                  />
                </div>
              </section>
            )}

            {step === 2 && (
              <section aria-labelledby="s3">
                <h1 id="s3" className="font-headline text-headline-lg text-on-primary-fixed">
                  {t('reviewTitle')}
                </h1>
                <p className="mt-2 text-body-md text-on-surface-variant">{t('reviewIntro')}</p>

                {formError && (
                  <div className="mt-6">{<FormBanner>{formError}</FormBanner>}</div>
                )}

                <dl className="mt-8 divide-y divide-outline-variant/40 rounded border border-outline-variant/40">
                  {(
                    [
                      [tc('fullName'), draft.full_name],
                      [tc('email'), draft.email],
                      [t('board'), draft.board],
                      [t('classLevel'), t('classOption', { level: draft.class_level })],
                      [
                        t('group'),
                        groupOptions.find((g) => g.value === draft.student_group)?.label ?? '',
                      ],
                      [t('medium'), draft.medium === 'en' ? t('mediumEn') : t('mediumUr')],
                    ] as const
                  ).map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-4 px-4 py-3">
                      <dt className="text-body-sm text-on-surface-variant">{label}</dt>
                      <dd className="text-body-sm font-semibold">{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
          </div>

          <div className="mt-10 flex items-center justify-between gap-4">
            {step > 0 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s - 1)}
                className="text-body-sm font-semibold text-on-surface-variant hover:text-primary"
              >
                {tc('back')}
              </button>
            ) : (
              <p className="text-body-sm text-on-surface-variant">
                {tc('haveAccount')}{' '}
                <a href={`/${locale}/login`} className="font-semibold text-primary underline">
                  {tc('signIn')}
                </a>
              </p>
            )}

            {step < 2 ? (
              <button
                type="button"
                disabled={step === 0 ? !basicComplete : !academicComplete}
                onClick={() => setStep((s) => s + 1)}
                className="rounded bg-primary-container px-6 py-3 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                {tc('continue')}
              </button>
            ) : (
              <button
                type="button"
                disabled={submitting || !basicComplete || !academicComplete}
                onClick={submit}
                className="rounded bg-primary-container px-6 py-3 text-body-md font-semibold text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? tc('submitting') : tc('submit')}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
