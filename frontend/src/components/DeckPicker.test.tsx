/** Deck picker: search filtering, checkbox selection, pills and Clear (FR-10.12). */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { JSX } from 'react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import type { ItemRow } from '../api'
import { DeckPicker } from './DeckPicker'

function row(key: string): ItemRow {
  return {
    key,
    status: 'ready',
    present: true,
    epoch: 1,
    recordUrl: null,
    approvedAt: null,
    reason: null,
    fields: {},
    decision: null,
    activeJob: null,
  }
}

const FIRST = row('Deviation-1-1')
const SECOND = row('Deviation-2-2')
const THIRD = row('Deviation-3-3')

function Harness({
  rows,
  initial = [],
}: {
  rows: ItemRow[]
  initial?: string[]
}): JSX.Element {
  const [selected, setSelected] = useState(initial)
  return <DeckPicker rows={rows} selected={selected} onSelected={setSelected} />
}

describe('DeckPicker', () => {
  it('filters the options by deviation key as the operator types', async () => {
    const user = userEvent.setup()
    render(<Harness rows={[FIRST, SECOND, THIRD]} />)

    const input = screen.getByRole('combobox', { name: 'Find and pin deviations' })
    await user.click(input)
    await user.type(input, '3-3')

    expect(screen.getByRole('option', { name: 'Deviation-3-3' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Deviation-1-1' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Deviation-2-2' })).not.toBeInTheDocument()
  })

  it('checks a deviation and shows it as a removable pill', async () => {
    const user = userEvent.setup()
    render(<Harness rows={[FIRST, SECOND, THIRD]} />)

    await user.click(screen.getByRole('combobox', { name: 'Find and pin deviations' }))
    await user.click(screen.getByRole('option', { name: 'Deviation-2-2' }))

    expect(
      screen.getByRole('button', { name: 'Remove Deviation-2-2' }),
    ).toBeInTheDocument()
    const selected = screen.getByRole('option', { name: 'Deviation-2-2' })
    expect(selected).toHaveAttribute('aria-selected', 'true')
    expect(within(selected).getByTestId('CheckmarkSolidIcon')).toBeInTheDocument()
  })

  it('unchecks from the pill and keeps the other pins', async () => {
    const user = userEvent.setup()
    render(<Harness rows={[FIRST, SECOND, THIRD]} initial={['Deviation-2-2', 'Deviation-3-3']} />)

    // The remove affordance appears while the field has focus, like Salt's pill input.
    await user.click(screen.getByRole('combobox', { name: 'Find and pin deviations' }))
    await user.click(screen.getByRole('button', { name: 'Remove Deviation-2-2' }))

    expect(
      screen.queryByRole('button', { name: 'Remove Deviation-2-2' }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Remove Deviation-3-3' }),
    ).toBeInTheDocument()
  })

  it('clears every pin and the search text', async () => {
    const user = userEvent.setup()
    render(<Harness rows={[FIRST, SECOND, THIRD]} initial={['Deviation-1-1', 'Deviation-3-3']} />)

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    expect(screen.queryByRole('button', { name: /Remove Deviation/ })).not.toBeInTheDocument()
    const input = screen.getByRole('combobox', { name: 'Find and pin deviations' })
    expect(input).toHaveValue('')

    await user.click(input)
    expect(screen.getByRole('option', { name: 'Deviation-1-1' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('ignores stale selected keys that are no longer deck rows', () => {
    render(
      <Harness rows={[FIRST]} initial={['Deviation-9-9']} />,
    )
    expect(screen.queryByRole('button', { name: /Remove Deviation/ })).not.toBeInTheDocument()
  })

  it('disables the field when the deck has no rows', () => {
    render(<Harness rows={[]} />)
    expect(screen.getByRole('combobox', { name: 'Find and pin deviations' })).toBeDisabled()
  })
})
