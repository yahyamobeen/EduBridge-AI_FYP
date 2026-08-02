import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import en from '@/messages/en.json'
import ur from '@/messages/ur.json'
import urLatn from '@/messages/ur-Latn.json'
import { Capabilities } from './Capabilities'
import { Hero } from './Hero'
import { Solutions } from './Solutions'

vi.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: ComponentProps<'a'> & { href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

// The shader backdrop owns WebGL and rAF; neither belongs in a content test.
vi.mock('@/components/motion/ShaderBackdrop', () => ({
  ShaderBackdrop: () => <div data-testid="backdrop" aria-hidden="true" />,
}))

type Messages = typeof en

function renderLanding(messages: Messages = en, locale = 'en', onError?: () => void) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages} onError={onError}>
      <Hero />
      <Solutions />
      <Capabilities />
    </NextIntlClientProvider>,
  )
}

describe('landing content', () => {
  it('has exactly one level-one heading', () => {
    renderLanding()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('reads as one sentence even though the headline is split for styling', () => {
    // The accent span is a gradient fragment, not a separate thought; it must
    // still be announced as part of the same heading.
    renderLanding()
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1).toHaveTextContent(en.landing.hero.titleLead)
    expect(h1).toHaveTextContent(en.landing.hero.titleAccent)
  })

  it('names the boards and classes a visitor is deciding about', () => {
    renderLanding()
    expect(screen.getAllByText(/PCTB/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/STBB/).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/9/)
  })

  it('addresses all three audiences', () => {
    renderLanding()
    for (const tag of [
      en.landing.solutions.students.tag,
      en.landing.solutions.teachers.tag,
      en.landing.solutions.parents.tag,
    ]) {
      expect(screen.getByText(tag)).toBeInTheDocument()
    }
  })

  it('shows the illustrative preview panels from the prototype', () => {
    renderLanding()
    expect(screen.getByText(en.landing.solutions.students.previewLabel)).toBeInTheDocument()
    expect(screen.getByText(en.landing.solutions.students.previewAsk)).toBeInTheDocument()
    expect(screen.getByText(en.landing.solutions.teachers.sampleTopic)).toBeInTheDocument()
    expect(screen.getByText(en.landing.solutions.parents.cardMasteryTitle)).toBeInTheDocument()
    expect(screen.getByText(en.landing.solutions.parents.cardPlannerTitle)).toBeInTheDocument()
  })
})

describe('motion', () => {
  it('marks animated sections so the reveal controller can find them', () => {
    const { container } = renderLanding()
    expect(container.querySelectorAll('.reveal, .stagger').length).toBeGreaterThan(0)
  })

  it('leaves parallax targets declaring their own speed', () => {
    const { container } = renderLanding()
    const targets = container.querySelectorAll('[data-parallax-speed]')
    expect(targets.length).toBeGreaterThan(0)
    for (const el of targets) {
      expect(Number.parseFloat(el.getAttribute('data-parallax-speed') ?? '')).toBeGreaterThan(0)
    }
  })

  it('hides every decorative icon from assistive technology', () => {
    const { container } = renderLanding()
    for (const svg of container.querySelectorAll('svg')) {
      expect(svg).toHaveAttribute('aria-hidden', 'true')
    }
  })
})

describe('links', () => {
  it('points every link at a real route, never at a placeholder', () => {
    // The supplied prototypes used href="#" throughout; a dead link in a demo
    // reads as a broken product.
    renderLanding()
    for (const link of screen.getAllByRole('link')) {
      const href = link.getAttribute('href')
      expect(href, link.textContent ?? '').toBeTruthy()
      expect(href, link.textContent ?? '').not.toBe('#')
    }
  })

  it('sends the primary call to action into sign-up', () => {
    renderLanding()
    expect(
      screen.getByRole('link', { name: new RegExp(en.landing.hero.ctaPrimary, 'i') }),
    ).toHaveAttribute('href', '/signup')
  })

  it('routes the institution action to coming-soon rather than a dead link', () => {
    // Kept from the prototype, but prd.md §15 CL-6 has no institutional route
    // in v1, so it must land somewhere real.
    renderLanding()
    expect(
      screen.getByRole('link', { name: new RegExp(en.landing.hero.ctaSecondary, 'i') }),
    ).toHaveAttribute('href', '/coming-soon/institutions')
  })

  it('anchors the solutions link to a section that exists', () => {
    const { container } = renderLanding()
    const anchor = screen.getByRole('link', {
      name: new RegExp(en.landing.hero.seeSolutions, 'i'),
    })
    const target = anchor.getAttribute('href')?.replace('#', '')
    expect(target).toBeTruthy()
    expect(container.querySelector(`#${target}`)).not.toBeNull()
  })
})

describe('role boundaries in the marketing copy', () => {
  it('does not promise parents access to their child tutoring conversations', () => {
    // prd.md §4.2 gives a parent no read path to chat content. The prototype's
    // parent dashboard offered a session replay button; the copy must not
    // advertise that capability either.
    renderLanding()
    const parentCard = screen.getByText(en.landing.solutions.parents.tag).closest('article')
    expect(parentCard).not.toBeNull()
    const copy = (parentCard as HTMLElement).textContent ?? ''
    // The prototype's own wording is "non-intrusive, secure progress reports",
    // which is compatible with the matrix. What must never appear is any
    // promise of access to the conversation itself.
    for (const forbidden of [/replay/i, /transcript/i, /conversation/i, /chat/i, /session/i]) {
      expect(copy, `parent copy must not promise ${forbidden}`).not.toMatch(forbidden)
    }
  })
})

describe('translations', () => {
  it.each([
    ['ur', ur],
    ['ur-Latn', urLatn],
  ])('renders fully in %s with no missing keys', (locale, messages) => {
    const onError = vi.fn()
    renderLanding(messages as Messages, locale, onError)
    // next-intl reports a missing key through onError rather than throwing, so
    // an untranslated string would otherwise pass silently.
    expect(onError).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      (messages as Messages).landing.hero.titleAccent,
    )
  })
})
