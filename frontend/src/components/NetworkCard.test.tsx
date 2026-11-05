/** Home network card: addresses, copy action and the loopback warning. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { NetworkView } from '../api'
import { NetworkCard } from './NetworkCard'

const NETWORK: NetworkView = {
  host: '0.0.0.0',
  port: 8765,
  lanIp: '192.168.1.42',
  lanUrl: 'http://192.168.1.42:8765',
  localUrl: 'http://127.0.0.1:8765',
  lanEnabled: true,
}

describe('NetworkCard', () => {
  it('shows the LAN URL and copies it', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    render(<NetworkCard network={NETWORK} />)

    expect(screen.getByText('http://192.168.1.42:8765')).toBeInTheDocument()
    expect(
      screen.getByText(/This device: http:\/\/127\.0\.0\.1:8765/),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(writeText).toHaveBeenCalledWith('http://192.168.1.42:8765')
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('explains a loopback bind', () => {
    render(
      <NetworkCard
        network={{ ...NETWORK, lanIp: null, lanUrl: null, lanEnabled: false }}
      />,
    )
    expect(screen.getByText(/LAN access is off/)).toBeInTheDocument()
  })
})
