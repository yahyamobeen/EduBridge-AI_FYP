import { AtomIcon, BookIcon, GlobeIcon, SparkIcon } from '@/components/ui/Icon'

/** A tutor book the student opened: what the chat view needs to know about it. */
export type OpenBook = {
  bookId: string
  /** The subject catalogue's name, e.g. "Physics", "Computer Science". */
  subject: string
  board: 'PCTB' | 'STBB'
  classLevel: number
}

/** The Physics 9 pilot book: the only one with quick-prompt chips. */
export const PHYSICS_BOOK = 'Punjab_9_Physics'

/**
 * The subject catalogue's names (backend `subject.name`) mapped to `tutor.subjects`
 * message keys. A name not listed here is shown as the server sent it, rather than
 * hidden - a missing translation must not lose a subject.
 */
const SUBJECT_KEYS: Record<string, string> = {
  Physics: 'physics',
  Mathematics: 'mathematics',
  Chemistry: 'chemistry',
  Biology: 'biology',
  'Computer Science': 'computerScience',
  English: 'english',
  Urdu: 'urdu',
  Islamiat: 'islamiyat',
  'Pakistan Studies': 'pakistanStudies',
  'Quran Translation': 'quranTranslation',
}

export function subjectKey(subject: string): string | null {
  return SUBJECT_KEYS[subject] ?? null
}

/** The localized name, falling back to the catalogue name. */
export function subjectLabel(subject: string, t: (key: string) => string): string {
  const key = subjectKey(subject)
  return key ? t(key) : subject
}

const SCIENCE = new Set(['Mathematics', 'Chemistry', 'Biology', 'Computer Science'])

/** The subject's icon. A component returning JSX, so no component is created during render. */
export function SubjectIcon({ subject, className }: { subject: string; className?: string }) {
  if (subject === 'Physics') return <AtomIcon className={className} />
  if (SCIENCE.has(subject)) return <SparkIcon className={className} />
  if (subject === 'English') return <GlobeIcon className={className} />
  return <BookIcon className={className} />
}
