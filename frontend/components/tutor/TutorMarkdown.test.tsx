import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TutorMarkdown } from './TutorMarkdown'

describe('TutorMarkdown', () => {
  it('renders bold as emphasis rather than literal asterisks', () => {
    const { container } = render(<TutorMarkdown content="According to **Table 1.4** (p10)." />)

    expect(container.querySelector('strong')).toHaveTextContent('Table 1.4')
    // The defect this component exists to fix: `**` reaching the student verbatim.
    expect(container.textContent).not.toContain('**')
  })

  it('renders LaTeX as real maths, not raw dollar-sign source', () => {
    // String.raw, because a plain '\frac' in a TS literal is a formfeed plus "rac",
    // which renders a KaTeX parse error that looks exactly like a component bug.
    const { container } = render(
      <TutorMarkdown
        content={String.raw`The formula is $$T_F = \frac{9}{5} \times T_c + 32$$`}
      />,
    )

    expect(container.querySelector('.katex')).not.toBeNull()
    expect(container.querySelector('.katex-error')).toBeNull()
    // A real stacked fraction, not merely something KaTeX accepted.
    expect(container.querySelector('mfrac')).not.toBeNull()
  })

  it('renders the degree and subscript notation the physics book uses', () => {
    const { container } = render(
      <TutorMarkdown content={String.raw`Given $T_c = 30^\circ\text{C}$ today`} />,
    )

    expect(container.querySelector('.katex')).not.toBeNull()
    expect(container.querySelector('.katex-error')).toBeNull()
    expect(container.querySelector('msub')).not.toBeNull()
  })

  it('renders bullet and numbered lists', () => {
    const { container } = render(
      <TutorMarkdown
        content={'* **Tera (T):** ten\n* **Peta (P):** eleven\n\n1. first\n2. second'}
      />,
    )

    expect(container.querySelectorAll('ul li')).toHaveLength(2)
    expect(container.querySelectorAll('ol li')).toHaveLength(2)
  })

  it('does not throw on half-written maths, which is every streamed frame', () => {
    // Frames arrive mid-token, so the tree is re-parsed against incomplete input on
    // the way to valid. Throwing here would blank the answer mid-stream.
    expect(() =>
      render(<TutorMarkdown content={String.raw`The formula is $$T_F = \frac{9`} />),
    ).not.toThrow()
  })

  it('escapes embedded HTML instead of executing it', () => {
    // Model output is data (tdd.md §4.6). `rehype-raw` is deliberately absent; if
    // anyone adds it to "support HTML in answers", this test fails.
    const { container } = render(
      <TutorMarkdown
        content={'<img src=x onerror="alert(1)"><script>alert(2)</script> after'}
      />,
    )

    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/after/)).toBeInTheDocument()
  })

  it('renders a generated link as text with no href', () => {
    // Any URL here is invented: the prompt forbids answering from anything but the
    // pages shown. A fabricated link dressed as a citation is what this prevents.
    const { container } = render(
      <TutorMarkdown content="See [the full notes](https://evil.example.com/pay) for more." />,
    )

    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('the full notes')
  })

  it('drops generated images', () => {
    const { container } = render(
      <TutorMarkdown content="![a diagram](https://evil.example.com/x.png)" />,
    )

    expect(container.querySelector('img')).toBeNull()
  })
})
