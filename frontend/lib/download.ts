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

/**
 * Show a file in a new tab through a short-lived link (classroom Phase 6b).
 *
 * The tab is opened FIRST, synchronously inside the click, because a pop-up
 * blocker allows a window opened by the click itself but not one opened after
 * an await. Only then is the link fetched and the tab pointed at it. `opener`
 * is cut so the storage service's page can never reach back into this one; if
 * the link cannot be had, the blank tab is closed and the error re-thrown.
 */
export async function openInNewTab(getUrl: () => Promise<string>): Promise<void> {
  const tab = window.open('', '_blank')
  if (!tab) throw new Error('The new tab was blocked.')
  tab.opener = null
  try {
    tab.location.href = await getUrl()
  } catch (caught) {
    tab.close()
    throw caught
  }
}
