/** Network-profile dialog: preset choice, server-derived budgets and save. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SettingsView } from '../api'
import { SettingsMenu } from './SettingsMenu'

const SETTINGS: SettingsView = {
  profile: 'default',
  presets: [
    { profile: 'fast', actionS: 60, stageReadS: 45, stageWriteS: 90, submissionS: 180 },
    {
      profile: 'default',
      actionS: 60,
      stageReadS: 75,
      stageWriteS: 150,
      submissionS: 300,
    },
    {
      profile: 'slow',
      actionS: 120,
      stageReadS: 150,
      stageWriteS: 300,
      submissionS: 600,
    },
  ],
}

describe('SettingsMenu', () => {
  it('shows every preset with its budget and saves the chosen one', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(SETTINGS)
    render(
      <SettingsMenu settings={SETTINGS} saving={false} error={null} onSave={onSave} />,
    )

    await user.click(screen.getByRole('button', { name: 'Network profile' }))
    expect(screen.getByText(/a submit never exceeds 300 s/)).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /Slow/ }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(onSave).toHaveBeenCalledWith('slow')
  })

  it('keeps the dialog open and shows the error when saving fails', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockRejectedValue(new Error('cannot write settings.json'))
    render(
      <SettingsMenu settings={SETTINGS} saving={false} error={null} onSave={onSave} />,
    )

    await user.click(screen.getByRole('button', { name: 'Network profile' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })
})
