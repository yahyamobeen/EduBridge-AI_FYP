import { fireEvent, render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { BackupCodes } from './BackupCodes'

/**
 * Finding A7: the download produced no file and no error.
 *
 * Two bugs in four lines — the anchor was never attached to the document, and
 * the object URL was revoked on the same tick as the click, destroying the blob
 * before the download read it. Chrome tolerated both; Firefox did not.
 *
 * WHY THAT IS EXPENSIVE HERE and not just an annoyance: these ten codes are
 * shown exactly once (SEC-14), and `TwoFactorEnrollment` leaves the step with
 * `router.replace`, so there is no way back. A silent failure loses them
 * permanently, and there is no regenerate endpoint.
 */

type Messages = typeof en

const CODES = ['BKUP0000', 'BKUP0001', 'BKUP0002']

function renderCodes(messages: Messages = en, locale = 'en', onError?: () => void) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages} onError={onError}>
      <BackupCodes codes={CODES} onContinue={vi.fn()} />
    </NextIntlClientProvider>,
  )
}

// jsdom implements neither, so they are installed before they can be spied on.
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => 'blob:stub'
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => undefined
}

let attachedAtClickTime: boolean | null = null

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  attachedAtClickTime = null
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:stub')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    // The whole point of the fix: a detached anchor is not reliably clickable.
    attachedAtClickTime = document.body.contains(this)
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function clickDownload() {
  fireEvent.click(screen.getByRole('button', { name: en.auth.backupCodes.download }))
}

describe('downloading the codes', () => {
  it('clicks an anchor that is attached to the document', () => {
    renderCodes()
    clickDownload()

    expect(attachedAtClickTime).toBe(true)
  })

  it('removes the anchor again, leaving no stray node behind', () => {
    renderCodes()
    clickDownload()

    expect(document.querySelectorAll('a[download]')).toHaveLength(0)
  })

  it('does NOT revoke the object URL on the same tick as the click', () => {
    renderCodes()
    clickDownload()

    // This is the bug, expressed directly: revoking here killed the blob before
    // the download started reading it.
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })

  it('revokes it once the tick has passed, so nothing leaks', () => {
    renderCodes()
    clickDownload()
    vi.runAllTimers()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:stub')
  })

  it('says so when the download fails, instead of failing silently', () => {
    vi.mocked(URL.createObjectURL).mockImplementation(() => {
      throw new Error('blocked')
    })
    renderCodes()
    clickDownload()

    // `copy()` already surfaced its failure and the file's own docstring says
    // the point is that "the failure is visible rather than silent" — this was
    // the one function that did not follow it.
    expect(screen.getByText(en.auth.backupCodes.downloadFailed)).toBeVisible()
  })

  it('shows no failure message on the happy path', () => {
    renderCodes()
    clickDownload()

    expect(screen.queryByText(en.auth.backupCodes.downloadFailed)).not.toBeInTheDocument()
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders fully in %s with no missing keys', (locale, messages) => {
    const onError = vi.fn()
    renderCodes(messages as Messages, locale, onError)
    // next-intl reports a missing key through onError rather than throwing, so
    // an untranslated `downloadFailed` would otherwise pass silently.
    expect(onError).not.toHaveBeenCalled()
  })
})
