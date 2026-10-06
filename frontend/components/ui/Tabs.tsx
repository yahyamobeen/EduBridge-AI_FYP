'use client'

import { useRef } from 'react'

export type TabItem<K extends string> = { key: K; label: string }

/**
 * An ARIA tablist (WAI-ARIA Authoring Practices, "Tabs with automatic
 * activation"): one tab in the Tab order at a time, arrow keys move between
 * them, Home/End jump to the ends.
 *
 * ⚠️ ARROW KEYS FOLLOW THE SCREEN, NOT THE SOURCE ORDER. Under `dir="rtl"` (Urdu)
 *    the first tab is drawn on the RIGHT, so ArrowRight must move towards the
 *    start of the list, not the end. Read from the computed direction rather
 *    than the locale, so the component is correct wherever it is mounted.
 *
 * The caller renders each panel with `id={tabPanelId(key)}`, `role="tabpanel"`
 * and `aria-labelledby={tabId(key)}`.
 */
export function Tabs<K extends string>({
  label,
  value,
  onChange,
  items,
}: {
  label: string
  value: K
  onChange: (key: K) => void
  items: TabItem<K>[]
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    const rtl = getComputedStyle(event.currentTarget).direction === 'rtl'
    const forward = rtl ? 'ArrowLeft' : 'ArrowRight'
    const backward = rtl ? 'ArrowRight' : 'ArrowLeft'
    let next: number | null = null
    if (event.key === forward) next = (index + 1) % items.length
    else if (event.key === backward) next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    if (next === null) return
    event.preventDefault()
    refs.current[next]?.focus()
    onChange(items[next]!.key)
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className="mb-6 flex gap-1 border-b border-outline-variant"
    >
      {items.map((item, index) => {
        const selected = item.key === value
        return (
          <button
            key={item.key}
            ref={(el) => {
              refs.current[index] = el
            }}
            type="button"
            role="tab"
            id={tabId(item.key)}
            aria-selected={selected}
            aria-controls={tabPanelId(item.key)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={`-mb-px border-b-2 px-4 py-2 text-body-md transition-colors ${
              selected
                ? 'border-primary font-semibold text-primary'
                : 'border-transparent text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

export const tabId = (key: string) => `tab-${key}`
export const tabPanelId = (key: string) => `panel-${key}`
