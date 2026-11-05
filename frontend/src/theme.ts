/**
 * Light/dark theme preference.
 *
 * The first visit follows the OS setting; once the operator toggles, the explicit
 * choice is persisted in localStorage and wins on later visits.
 */

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'bl-theme-mode'

/** Read the saved or OS-preferred mode. */
export function initialMode(): ThemeMode {
  if (typeof window === 'undefined') return 'light'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  if (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark'
  }
  return 'light'
}

/** The other mode. */
export function nextMode(mode: ThemeMode): ThemeMode {
  return mode === 'light' ? 'dark' : 'light'
}

/** Persist the explicit operator choice. */
export function persistMode(mode: ThemeMode): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, mode)
}
