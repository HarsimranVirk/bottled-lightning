/** Footer: app version, quiet session/sync status and the manual refresh. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SessionView, SyncView } from '../api'
import { AppFooter } from './AppFooter'

const SESSION: SessionView = {
  state: 'valid',
  paused: false,
  cookies: 34,
  savedAt: '2026-11-04T15:20:40Z',
  lastEvent: null,
}

const SYNC: SyncView = {
  workflow: 'deviations_z02',
  capturedAt: new Date().toISOString(),
  headerTotal: 7,
  rowsRead: 7,
  valid: true,
  warning: null,
  added: 0,
  updated: 7,
  closed: 0,
}

const props = {
  version: '1.2.3',
  session: SESSION,
  sync: SYNC,
  onRefresh: vi.fn(),
  refreshing: false,
}

describe('AppFooter', () => {
  it('shows the version and the healthy session/sync status', () => {
    render(<AppFooter {...props} />)
    expect(screen.getByText('bottled-lightning v1.2.3')).toBeInTheDocument()
    expect(screen.getByText(/Session active · synced .* · 7 rows/)).toBeInTheDocument()
  })

  it('reflects a session that is not valid', () => {
    render(<AppFooter {...props} session={{ ...SESSION, state: 'expired', paused: true }} />)
    expect(screen.getByText('Session expired')).toBeInTheDocument()
  })

  it('flags an untrusted refresh without hiding the version', () => {
    render(<AppFooter {...props} sync={{ ...SYNC, valid: false, warning: 'header total not readable' }} />)
    expect(screen.getByText('Session active · last refresh untrusted')).toBeInTheDocument()
    expect(screen.getByText('bottled-lightning v1.2.3')).toBeInTheDocument()
  })

  it('refreshes on demand', async () => {
    const user = userEvent.setup()
    const onRefresh = vi.fn()
    render(<AppFooter {...props} onRefresh={onRefresh} />)
    await user.click(screen.getByRole('button', { name: 'Sync now' }))
    expect(onRefresh).toHaveBeenCalled()
  })
})
