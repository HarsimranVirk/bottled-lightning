/** Header control that switches the app between light and dark mode. */

import type { JSX } from 'react'
import { Button } from '@salt-ds/core'
import { DarkSolidIcon, LightSolidIcon } from '@salt-ds/icons'

import { nextMode } from '../theme'
import type { ThemeMode } from '../theme'

interface Props {
  mode: ThemeMode
  onToggle: () => void
}

/**
 * One icon button showing the mode it will switch to.
 *
 * The icon is decorative; the accessible name and tooltip always describe the action,
 * so the control is usable with a keyboard and a screen reader.
 */
export function ThemeToggle({ mode, onToggle }: Props): JSX.Element {
  const target = nextMode(mode)
  const label = `Switch to ${target} mode`
  const Icon = target === 'dark' ? DarkSolidIcon : LightSolidIcon
  return (
    <Button
      appearance="bordered"
      onClick={onToggle}
      aria-label={label}
      title={label}
      data-testid="theme-toggle"
    >
      <Icon aria-hidden />
    </Button>
  )
}
