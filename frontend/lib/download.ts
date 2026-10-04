/**
 * Hand a downloaded Blob to the browser as a saved file — never opened inside
 * the application (prd.md CL-8). The technique `BackupCodes.tsx` uses: a
 * temporary object URL on a temporary link, revoked on the NEXT tick, because
 * revoking synchronously cancels the download before it has read the blob.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
