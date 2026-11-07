/** Home update card: availability, install action, restart and retry states. */

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

const FAILED: UpdateStatus = {
  status: 'failed',
  updateAvailable: false,
  detail: 'URLError: offline',
  error: 'offline',
  latest: null,
  downloadUrl: null,
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
        checking={false}
        onInstall={onInstall}
        onCheck={vi.fn()}
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
        checking={false}
        onInstall={vi.fn()}
        onCheck={vi.fn()}
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
        checking={false}
        onInstall={vi.fn()}
        onCheck={vi.fn()}
      />,
    )
    expect(screen.getByText(/the app will restart/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Install update' })).toBeNull()
  })

  it('shows a failed check', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={FAILED}
        installing={false}
        busy={false}
        checking={false}
        onInstall={vi.fn()}
        onCheck={vi.fn()}
      />,
    )
    expect(screen.getByText(/Update check failed: offline/)).toBeInTheDocument()
  })

  it('forces a retry after a failed check', async () => {
    const user = userEvent.setup()
    const onCheck = vi.fn()
    render(
      <UpdateCard
        version="0.3.0"
        update={FAILED}
        installing={false}
        busy={false}
        checking={false}
        onInstall={vi.fn()}
        onCheck={onCheck}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Check again' }))
    expect(onCheck).toHaveBeenCalledTimes(1)
  })

  it('disables the retry while the check runs', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={FAILED}
        installing={false}
        busy={false}
        checking
        onInstall={vi.fn()}
        onCheck={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /checking/i })).toBeDisabled()
  })

  it('offers no retry when the check succeeded', () => {
    render(
      <UpdateCard
        version="0.3.0"
        update={{ ...AVAILABLE, status: 'up-to-date', updateAvailable: false }}
        installing={false}
        busy={false}
        checking={false}
        onInstall={vi.fn()}
        onCheck={vi.fn()}
      />,
    )
    expect(screen.getByText('Up to date.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull()
  })
})
