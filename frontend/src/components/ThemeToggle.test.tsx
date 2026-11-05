/** The header theme toggle: action label and click behaviour. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ThemeToggle } from './ThemeToggle'

describe('ThemeToggle', () => {
  it('offers the opposite mode and calls the handler', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    render(<ThemeToggle mode="light" onToggle={onToggle} />)

    const button = screen.getByRole('button', { name: 'Switch to dark mode' })
    await user.click(button)
    expect(onToggle).toHaveBeenCalledOnce()
  })

  it('labels the dark-mode button as a switch to light', () => {
    render(<ThemeToggle mode="dark" onToggle={vi.fn()} />)
    expect(
      screen.getByRole('button', { name: 'Switch to light mode' }),
    ).toBeInTheDocument()
  })
})
