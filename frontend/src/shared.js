// Shared helpers across pages.
const LS_KEY = 'bl.session-info'

export function loadStored() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) ?? null
  } catch {
    return null
  }
}

export function saveStored(info) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      ...info,
      checked_at: new Date().toISOString(),
    }))
  } catch { /* storage unavailable — non-fatal */ }
}

export function formatAge(seconds) {
  if (seconds == null) return null
  if (seconds < 90) return 'just now'
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 129600) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}
