/**
 * The file rules the browser can check before sending (classroom Phases 6 and
 * 6b) — shared by the file list, the student's work and the assignment form.
 *
 * The SERVER is the check: it reads the type from the bytes and enforces every
 * limit and quota. These only save someone waiting on an upload that is certain
 * to be refused.
 */

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const ACCEPT = '.pdf,.png,.jpg,.jpeg,.docx,.pptx'
const EXTENSIONS = new Set(['pdf', 'png', 'jpg', 'jpeg', 'docx', 'pptx'])

/** A `classroom.files` message key when the file is certain to be refused. */
export function earlyRefusal(file: File): 'unsupportedType' | 'tooLarge' | 'empty' | null {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!EXTENSIONS.has(extension)) return 'unsupportedType'
  if (file.size > MAX_UPLOAD_BYTES) return 'tooLarge'
  if (file.size === 0) return 'empty'
  return null
}

/**
 * What a browser can show by itself. Word and PowerPoint stay download-only:
 * the online viewers that could show them would hand a student's file to a
 * third party (owner decision 2026-10-05).
 */
export function isViewable(contentType: string): boolean {
  return ['application/pdf', 'image/png', 'image/jpeg'].includes(contentType)
}
