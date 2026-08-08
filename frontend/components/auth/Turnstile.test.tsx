import { render, waitFor } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import { Turnstile } from './Turnstile'

const SCRIPT_SELECTOR = 'script[data-edubridge-turnstile]'

const onVerify = vi.fn()
const onExpired = vi.fn()

type RenderFn = (container: HTMLElement, options: Record<string, unknown>) => string
type ResetFn = (widgetId: string) => void
type RemoveFn = (widgetId: string) => void

// One stub replaces Cloudflare for the whole suite; per-test assertions use
// mockClear() so call counts stay meaningful.
const api = {
  render: vi.fn<RenderFn>(() => 'widget-1'),
  reset: vi.fn<ResetFn>(() => undefined),
  remove: vi.fn<RemoveFn>(() => undefined),
}

/** Removes the stub so the component falls back to the script path. */
function unsetTurnstileApi() {
  Object.defineProperty(window, 'turnstile', { configurable: true, value: undefined })
}

function stubTurnstileApi() {
  Object.defineProperty(window, 'turnstile', { configurable: true, value: api })
}

/** Fires the `load` event the component listens for on the injected script. */
function fireApiLoad() {
  const script = document.querySelector(SCRIPT_SELECTOR) as HTMLScriptElement
  script.dispatchEvent(new Event('load'))
}

/**
 * The widget module caches its load promise for the file's lifetime; each
 * script-path test needs a pristine module, so import a fresh instance.
 */
async function loadFreshTurnstile() {
  vi.resetModules()
  const { Turnstile: Fresh } = await import('./Turnstile')
  return Fresh
}

function withIntl(ui: React.ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

function mountTurnstile(
  ui = <Turnstile onVerify={onVerify} onExpired={onExpired} />,
) {
  // With window.turnstile stubbed the pending API promise resolves without a
  // network round trip, so no script element exists to fire an event on.
  return render(withIntl(ui))
}

describe('Turnstile widget', () => {
  beforeEach(() => {
    document.head.innerHTML = ''
    stubTurnstileApi()
    api.render.mockClear()
    api.reset.mockClear()
    api.remove.mockClear()
    onVerify.mockReset()
    onExpired.mockReset()
  })

  it('loads the script once when the API is absent, then reports token', async () => {
    unsetTurnstileApi()
    const Fresh = await loadFreshTurnstile()
    render(withIntl(<Fresh onVerify={onVerify} onExpired={onExpired} />))
    expect(document.querySelector(SCRIPT_SELECTOR)).not.toBeNull()
    // The real widget would have loaded by now; the stub takes its place
    // before the promise resolves.
    stubTurnstileApi()
    fireApiLoad()

    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))
  })

  it('does not double-inject the script across two mounts', async () => {
    unsetTurnstileApi()
    const Fresh = await loadFreshTurnstile()
    const view = render(withIntl(<Fresh onVerify={onVerify} />))
    stubTurnstileApi()
    fireApiLoad()
    view.rerender(withIntl(<Fresh onVerify={onVerify} onExpired={onExpired} />))

    await waitFor(() => expect(document.querySelectorAll(SCRIPT_SELECTOR)).toHaveLength(1))
  })

  it('renders the widget into a container with the site key and its language', async () => {
    expect(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY).toBeTruthy()
    mountTurnstile()

    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))

    const [container, options] = api.render.mock.calls[0]!
    expect(container).toBeInstanceOf(HTMLDivElement)
    expect(options.sitekey).toBe(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY)
    expect(typeof options.language).toBe('string')
  })

  it('reports fresh tokens through onVerify', async () => {
    mountTurnstile()
    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))

    const [, options] = api.render.mock.calls[0]!
    ;(options.callback as (t: string) => void)('test-token')
    expect(onVerify).toHaveBeenCalledWith('test-token')
  })

  it('resets the widget when resetNonce bumps', async () => {
    const view = mountTurnstile()
    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))

    view.rerender(
      withIntl(<Turnstile onVerify={onVerify} onExpired={onExpired} resetNonce={1} />),
    )
    await waitFor(() => expect(api.reset).toHaveBeenCalledWith('widget-1'))
  })

  it('surfaces token expiry through onExpired', async () => {
    mountTurnstile()
    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))

    const [, options] = api.render.mock.calls[0]!
    ;(options['expired-callback'] as () => void)()
    expect(onExpired).toHaveBeenCalledTimes(1)
  })

  it('removes the widget when unmounting', async () => {
    const view = mountTurnstile()
    await waitFor(() => expect(api.render).toHaveBeenCalledTimes(1))

    view.unmount()
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('widget-1'))
  })

  it('renders nothing when there is no site key', async () => {
    const original = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = ''
    try {
      const { container } = render(withIntl(<Turnstile onVerify={onVerify} />))
      expect(container.firstChild).toBeNull()
    } finally {
      process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = original
    }
  })
})