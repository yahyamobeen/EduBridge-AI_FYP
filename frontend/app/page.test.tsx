import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Page from './page'

// Smoke test: proves the harness (jsdom + Testing Library + tsconfig paths +
// the React plugin) actually renders a component from this app.
describe('root page', () => {
  it('renders the product name as a heading', () => {
    render(<Page />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('EduBridge AI')
  })
})
