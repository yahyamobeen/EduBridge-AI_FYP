import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Tabs } from './Tabs'

/**
 * The tablist keyboard contract (WAI-ARIA "Tabs with automatic activation").
 * The RTL case is the one that matters here: in Urdu the first tab is drawn on
 * the right, so ArrowRight must move towards the START of the list.
 */

type Key = 'a' | 'b' | 'c'

function Harness({ dir }: { dir?: 'rtl' }) {
  const [value, setValue] = useState<Key>('a')
  return (
    <div dir={dir} style={dir ? { direction: 'rtl' } : undefined}>
      <Tabs<Key>
        label="Sections"
        value={value}
        onChange={setValue}
        items={[
          { key: 'a', label: 'Alpha' },
          { key: 'b', label: 'Beta' },
          { key: 'c', label: 'Gamma' },
        ]}
      />
    </div>
  )
}

const selected = () =>
  screen.getAllByRole('tab').find((t) => t.getAttribute('aria-selected') === 'true')
    ?.textContent

describe('Tabs', () => {
  it('keeps exactly one tab in the Tab order', () => {
    render(<Harness />)
    const tabIndexes = screen.getAllByRole('tab').map((t) => t.getAttribute('tabindex'))
    expect(tabIndexes).toEqual(['0', '-1', '-1'])
  })

  it('moves with the arrow keys and wraps, left to right', async () => {
    render(<Harness />)
    screen.getByRole('tab', { name: 'Alpha' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(selected()).toBe('Beta')
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
    expect(selected()).toBe('Gamma')
    await userEvent.keyboard('{Home}')
    expect(selected()).toBe('Alpha')
  })

  it('reverses the arrows right to left', async () => {
    render(<Harness dir="rtl" />)
    screen.getByRole('tab', { name: 'Alpha' }).focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(selected()).toBe('Beta')
    await userEvent.keyboard('{End}')
    expect(selected()).toBe('Gamma')
  })
})
