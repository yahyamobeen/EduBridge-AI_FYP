/**
 * The prototypes used the Material Symbols icon font, fetched from Google at
 * runtime — a third-party request in the critical path (prd.md A11Y-2). These
 * are inline equivalents: no network cost, no layout shift while a font loads.
 *
 * All are decorative and sit beside a real text label, so all are hidden from
 * assistive technology.
 */

type IconProps = { className?: string }

function Svg({ className, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  )
}

export function CheckIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 10.5 8 14.5 16 6" />
    </Svg>
  )
}

/**
 * Points in the reading direction, so callers add `rtl:-scale-x-100`. Not baked
 * in, because the same glyph is occasionally used where direction is not
 * meaningful.
 */
export function ArrowIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 10h12M11 5l5 5-5 5" />
    </Svg>
  )
}

export function ChevronDownIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M5 7.5 10 12.5 15 7.5" />
    </Svg>
  )
}

export function ShieldIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M10 2.5 16 5.2V10c0 3.5-2.5 5.8-6 7.5C6.5 15.8 4 13.5 4 10V5.2z" />
      <path d="M7.6 10.1 9.3 11.8 12.6 8.5" />
    </Svg>
  )
}

export function BookIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M3.5 4.5H8a2 2 0 0 1 2 2V16a2 2 0 0 0-2-1.6H3.5z" />
      <path d="M16.5 4.5H12a2 2 0 0 0-2 2V16a2 2 0 0 1 2-1.6h4.5z" />
    </Svg>
  )
}

export function ChatIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M16.5 12.5A1.5 1.5 0 0 1 15 14H7l-3.5 3V5A1.5 1.5 0 0 1 5 3.5h10A1.5 1.5 0 0 1 16.5 5z" />
    </Svg>
  )
}

export function ChartIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M3.5 16.5h13" />
      <path d="M6 16.5V9M10 16.5V4.5M14 16.5v-5" />
    </Svg>
  )
}

export function GlobeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M2.5 10h15" />
      <path d="M10 2.5c2 2.2 3 4.8 3 7.5s-1 5.3-3 7.5c-2-2.2-3-4.8-3-7.5s1-5.3 3-7.5z" />
    </Svg>
  )
}

export function UsersIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="7.5" cy="7" r="2.75" />
      <path d="M3 16.5c0-2.5 2-4.25 4.5-4.25S12 14 12 16.5" />
      <path d="M13.5 6.2a2.6 2.6 0 0 1 0 5.1" />
      <path d="M14.5 12.6c1.6.5 2.7 1.9 2.7 3.9" />
    </Svg>
  )
}

export function SparkIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M10 3.2 11.7 7.6 16 9.3l-4.3 1.7L10 15.4 8.3 11 4 9.3l4.3-1.7z" />
    </Svg>
  )
}

export function CalendarIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="3.5" y="4.5" width="13" height="12" rx="1.75" />
      <path d="M3.5 8.5h13M7 3v3M13 3v3" />
    </Svg>
  )
}

export function TeachIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M2.5 7 10 3.5 17.5 7 10 10.5z" />
      <path d="M5.5 8.6V13c0 1.4 2 2.5 4.5 2.5s4.5-1.1 4.5-2.5V8.6" />
    </Svg>
  )
}
