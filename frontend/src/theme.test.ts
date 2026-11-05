/** Theme preference: saved choice, OS default and persistence. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { initialMode, nextMode, persistMode } from './theme'

function setOSDark(dark: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: dark,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }))
}

describe('theme preference', () => {
  beforeEach(() => {
    window.localStorage.clear()
    setOSDark(false)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('follows the OS setting on a first visit', () => {
    setOSDark(true)
    expect(initialMode()).toBe('dark')
    setOSDark(false)
    expect(initialMode()).toBe('light')
  })

  it('prefers the saved operator choice over the OS', () => {
    window.localStorage.setItem('bl-theme-mode', 'light')
    setOSDark(true)
    expect(initialMode()).toBe('light')
  })

  it('falls back to light when matchMedia is unavailable', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(initialMode()).toBe('light')
  })

  it('toggles and persists the explicit choice', () => {
    expect(nextMode('light')).toBe('dark')
    expect(nextMode('dark')).toBe('light')
    persistMode('dark')
    expect(window.localStorage.getItem('bl-theme-mode')).toBe('dark')
  })
})
