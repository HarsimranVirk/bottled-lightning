/** Home update card: availability, install action and restart states. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { UpdateStatus } from '../api'
import { UpdateCard } from './UpdateCard'

const AVAILABLE: UpdateStatus = {
  status: 'update-available',
  updateAvailable: true,
  detail: 'ok',
  error: null,
  latest: 'v0.4.0',
  downloadUrl: 'https://github.com/o/r/x.whl',
}

describe('UpdateCard', () => {
  it('installs when the app is idle', async () => {
    const user = userEvent.setup()
    const onInstall = vi.fn()
    render(
      <UpdateCard
        version="0.3.0"
        update={AVAILABLE}
        installing={false}
        busy={false}
        onInstall={onInstall}
      />,
    )

    expect(screen.getByText('Version 0.3.0')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Install update' }))
    expect(onInstall).toHaveBeenCalledTimes(1)
  })

  it('disables the action while jobs run', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={AVAILABLE}
        installing={false}
        busy
        onInstall={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Install update' })).toBeDisabled()
    expect(screen.getByText(/wait for the running jobs/i)).toBeInTheDocument()
  })

  it('shows the restarting state', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={{ ...AVAILABLE, status: 'installing' }}
        installing
        busy={false}
        onInstall={vi.fn()}
      />,
    )
    expect(screen.getByText(/the app will restart/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Install update' })).toBeNull()
  })

  it('shows a failed check', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={{
          status: 'failed',
          updateAvailable: false,
          detail: 'offline',
          error: 'offline',
          latest: null,
          downloadUrl: null,
        }}
        installing={false}
        busy={false}
        onInstall={vi.fn()}
      />,
    )
    expect(screen.getByText(/Update check failed: offline/)).toBeInTheDocument()
  })
})
