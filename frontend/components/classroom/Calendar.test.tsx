import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CalendarItem } from '@/lib/api/types'
import { gridRange, monthGrid } from '@/lib/calendar'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { CalendarView } from './Calendar'

/**
 * The calendar. What must hold: it asks for exactly the grid's range (the
 * user's local month, Monday-first); each entry links back into its classroom —
 * an assignment straight to Classwork, an announcement to the classroom; a
 * student's due entry carries the status the SERVER derived; and moving month
 * asks for the new range rather than reusing the old one.
 */

const getCalendar = vi.fn()
vi.mock('@/lib/api/endpoints', () => ({
  getCalendar: (...a: unknown[]) => getCalendar(...a),
}))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

const LOADED = { timeout: 5_000 }
const OCTOBER = new Date(2026, 9, 15)

function item(overrides: Partial<CalendarItem> = {}): CalendarItem {
  return {
    kind: 'due',
    // Midday UTC: the same local date in every time zone a test machine is in.
    at: '2026-10-20T12:00:00Z',
    space_id: 'space-1',
    space_title: 'Physics 11-A',
    ref_id: 'as-1',
    title: 'Lab 1',
    my_status: 'missing',
    ...overrides,
  }
}

function renderView(locale = 'en', messages: typeof en = en, onError?: () => void) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Asia/Karachi"
      {...(onError ? { onError } : {})}
    >
      <CalendarView basePath="/classroom" start={OCTOBER} />
    </NextIntlClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getCalendar.mockResolvedValue({ items: [], truncated: false })
})

describe('the month', () => {
  it("asks for exactly the grid's range", async () => {
    renderView()
    expect(await screen.findByText('October 2026', {}, LOADED)).toBeInTheDocument()
    const { from, to } = gridRange(monthGrid(2026, 9))
    expect(getCalendar).toHaveBeenCalledWith(from, to, expect.any(AbortSignal))
  })

  it('moves to the next month and asks for its range', async () => {
    renderView()
    await screen.findByText('October 2026', {}, LOADED)
    await userEvent.click(screen.getByRole('button', { name: en.classroom.calendar.next }))
    expect(await screen.findByText('November 2026')).toBeInTheDocument()
    const { from, to } = gridRange(monthGrid(2026, 10))
    await waitFor(() =>
      expect(getCalendar).toHaveBeenLastCalledWith(from, to, expect.any(AbortSignal)),
    )
  })

  it('says when nothing is due', async () => {
    renderView()
    expect(await screen.findByText(en.classroom.calendar.empty, {}, LOADED)).toBeInTheDocument()
  })

  it('says when it could not load', async () => {
    getCalendar.mockRejectedValue(new Error('network'))
    renderView()
    expect(await screen.findByRole('alert', {}, LOADED)).toHaveTextContent(
      en.classroom.calendar.loadFailed,
    )
  })
})

describe('entries', () => {
  it("link back into the classroom, with the server's status", async () => {
    getCalendar.mockResolvedValue({
      items: [
        item(),
        item({
          kind: 'scheduled_announcement',
          ref_id: 'an-1',
          title: 'Test on Monday',
          my_status: null,
          at: '2026-10-21T12:00:00Z',
        }),
      ],
      truncated: false,
    })
    renderView()
    const due = (await screen.findByText('Lab 1', {}, LOADED)).closest('a')!
    expect(due).toHaveAttribute('href', '/classroom/space-1?assignment=as-1')
    expect(within(due).getByText(en.classroom.status.missing)).toBeInTheDocument()
    expect(within(due).getByText(/Due/)).toBeInTheDocument()

    const post = screen.getByText('Test on Monday').closest('a')!
    expect(post).toHaveAttribute('href', '/classroom/space-1')
    expect(within(post).getByText(/Announcement goes live/)).toBeInTheDocument()
    expect(screen.queryByText(en.classroom.calendar.empty)).toBeNull()
  })

  it('warns when the range held more than can be shown', async () => {
    getCalendar.mockResolvedValue({ items: [item()], truncated: true })
    renderView()
    expect(await screen.findByRole('alert', {}, LOADED)).toHaveTextContent(
      en.classroom.calendar.truncated,
    )
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])(
    'renders a month with every kind of entry in %s with no missing keys',
    async (locale, messages) => {
      const onError = vi.fn()
      getCalendar.mockResolvedValue({
        items: [
          item(),
          item({ kind: 'scheduled_assignment', ref_id: 'as-2', my_status: null }),
          item({ kind: 'scheduled_announcement', ref_id: 'an-1', my_status: null }),
        ],
        truncated: true,
      })
      renderView(locale, messages as typeof en, onError)
      expect(await screen.findAllByText('Lab 1', {}, LOADED)).toHaveLength(3)
      expect(onError).not.toHaveBeenCalled()
    },
  )
})
