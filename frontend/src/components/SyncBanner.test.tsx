/** Global banner: only problems are surfaced; the footer carries the healthy state. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { SessionView, SyncView } from '../api'
import { SyncBanner } from './SyncBanner'

const SESSION: SessionView = {
  state: 'valid',
  paused: false,
  cookies: 34,
  savedAt: '2026-11-04T15:20:40Z',
  lastEvent: null,
}

function sync(overrides: Partial<SyncView> = {}): SyncView {
  return {
    workflow: 'deviations_z02',
    capturedAt: new Date().toISOString(),
    headerTotal: 7,
    rowsRead: 7,
    valid: true,
    warning: null,
    added: 0,
    updated: 7,
    closed: 0,
    ...overrides,
  }
}

const props = {
  onLogin: vi.fn(),
  onRefresh: vi.fn(),
  refreshing: false,
}

describe('SyncBanner', () => {
  it('stays quiet when the session and the sync are healthy', () => {
    const { container } = render(<SyncBanner session={SESSION} sync={sync()} {...props} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('tells the operator how old an untrusted refresh is', () => {
    const capturedAt = new Date(Date.now() - 2 * 60_000).toISOString()
    render(
      <SyncBanner
        session={SESSION}
        sync={sync({
          valid: false,
          warning: 'header total not readable',
          capturedAt,
          headerTotal: null,
          rowsRead: 0,
        })}
        {...props}
      />,
    )
    expect(screen.getByText(/header total not readable/)).toBeInTheDocument()
    expect(screen.getByText(/checked 2 min ago/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry sync' })).toBeInTheDocument()
  })

  it('asks for a login when the session is not valid', () => {
    render(
      <SyncBanner
        session={{ ...SESSION, state: 'expired', paused: true }}
        sync={sync()}
        {...props}
      />,
    )
    expect(screen.getByText(/Jobs are paused/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log in' })).toBeInTheDocument()
  })
})
