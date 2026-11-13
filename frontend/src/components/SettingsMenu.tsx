/** Header control: choose the network profile the browser runs under. */

import { useState } from 'react'
import type { JSX } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogCloseButton,
  DialogContent,
  DialogHeader,
  RadioButton,
  RadioButtonGroup,
  Text,
} from '@salt-ds/core'
import { SettingsSolidIcon } from '@salt-ds/icons'

import type { NetworkProfile, SettingsView, TimeoutPreset } from '../api'

/** Plain-language name for each profile; the numbers always come from the server. */
const TITLES: Record<NetworkProfile, string> = {
  fast: 'Fast — office wifi',
  default: 'Default — shipped setting',
  slow: 'Slow — VPN or congested link',
}

interface Props {
  settings: SettingsView | undefined
  saving: boolean
  error: string | null
  onSave: (profile: NetworkProfile) => Promise<unknown>
}

function PresetLabel({ preset }: { preset: TimeoutPreset }): JSX.Element {
  return (
    <span>
      {TITLES[preset.profile]} — a submit never exceeds {preset.submissionS} s
    </span>
  )
}

/**
 * Gear button and the profile dialog it opens.
 *
 * The dialog only renders numbers the server derived for each preset, so the budgets
 * live in one place (the backend) and the client never does arithmetic. Saving applies
 * the profile to the next job; a running job keeps the budget it started with.
 */
export function SettingsMenu({ settings, saving, error, onSave }: Props): JSX.Element {
  const [open, setOpen] = useState(false)
  const [chosen, setChosen] = useState<NetworkProfile | null>(null)
  const presets = settings?.presets ?? []
  const current = chosen ?? settings?.profile ?? null
  const selected = presets.find((preset) => preset.profile === current) ?? null

  function change(next: boolean): void {
    setOpen(next)
    if (next) setChosen(null)
  }

  async function save(): Promise<void> {
    if (current === null) return
    try {
      await onSave(current)
      change(false)
    } catch {
      // The error prop renders the message; the dialog stays open to retry.
    }
  }

  function pick(value: string): void {
    const preset = presets.find((item) => item.profile === value)
    if (preset) setChosen(preset.profile)
  }

  return (
    <>
      <Button
        appearance="bordered"
        aria-label="Network profile"
        title="Network profile"
        data-testid="settings-menu"
        onClick={() => change(true)}
      >
        <SettingsSolidIcon aria-hidden />
      </Button>
      <Dialog open={open} onOpenChange={change} size="small">
        <DialogHeader
          header="Network profile"
          description="How long a submission may take on this machine. Applies to the next job."
          actions={<DialogCloseButton onClick={() => change(false)} />}
        />
        <DialogContent>
          <RadioButtonGroup
            direction="vertical"
            value={current ?? undefined}
            onChange={(event) => pick(event.target.value)}
          >
            {presets.map((preset) => (
              <RadioButton
                key={preset.profile}
                value={preset.profile}
                label={<PresetLabel preset={preset} />}
              />
            ))}
          </RadioButtonGroup>
          {selected === null ? null : (
            <Text color="secondary">
              One action {selected.actionS} s · object read {selected.stageReadS} s ·
              object write {selected.stageWriteS} s · whole run{' '}
              {selected.submissionS} s
            </Text>
          )}
          {error === null ? null : <Text color="secondary">{error}</Text>}
        </DialogContent>
        <DialogActions>
          <Button appearance="bordered" onClick={() => change(false)}>
            Cancel
          </Button>
          <Button
            appearance="bordered"
            disabled={current === null || saving}
            onClick={() => {
              void save()
            }}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
