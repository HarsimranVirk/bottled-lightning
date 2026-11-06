/** Combined table filter: one ComboBox carrying the text filter and exact values (FR-9.18–9.21). */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { JSX } from 'react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { TableFilter } from './TableFilter'
import type { TableFilterOption } from './TableFilter'

const OPTIONS: TableFilterOption[] = [
  { value: 'ready', label: 'Ready' },
  { value: 'completed', label: 'Implemented' },
  { value: 'skipped', label: 'Skipped' },
]

function Harness({
  textMode,
  onText = vi.fn(),
  onSelected = vi.fn(),
  initialText = '',
  initialSelected = [],
}: {
  textMode?: 'filter' | 'search'
  onText?: (text: string) => void
  onSelected?: (values: string[]) => void
  initialText?: string
  initialSelected?: string[]
}): JSX.Element {
  const [text, setText] = useState(initialText)
  const [selected, setSelected] = useState(initialSelected)
  return (
    <TableFilter
      label="Filter by status"
      text={text}
      onText={(next) => {
        setText(next)
        onText(next)
      }}
      selected={selected}
      onSelected={(next) => {
        setSelected(next)
        onSelected(next)
      }}
      options={OPTIONS}
      textMode={textMode}
    />
  )
}

describe('TableFilter', () => {
  it('is one combobox rather than a text box plus a values dropdown', () => {
    render(<Harness />)
    expect(
      screen.getAllByRole('combobox', { name: 'Filter by status' }),
    ).toHaveLength(1)
    expect(screen.queryByLabelText('Filter by status values')).not.toBeInTheDocument()
  })

  it('keeps the typed text as the column filter in filter mode', async () => {
    const user = userEvent.setup()
    const onText = vi.fn()
    render(<Harness onText={onText} />)

    const input = screen.getByRole('combobox', { name: 'Filter by status' })
    await user.type(input, 'rea')

    expect(onText).toHaveBeenLastCalledWith('rea')
    expect(input).toHaveValue('rea')
    expect(screen.getByRole('option', { name: 'Ready' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Skipped' })).not.toBeInTheDocument()
  })

  it('checks several values and shows them as removable pills', async () => {
    const user = userEvent.setup()
    const onSelected = vi.fn()
    render(<Harness onSelected={onSelected} />)

    await user.click(screen.getByRole('combobox', { name: 'Filter by status' }))
    await user.click(screen.getByRole('option', { name: 'Skipped' }))
    await user.click(screen.getByRole('option', { name: 'Implemented' }))

    expect(onSelected).toHaveBeenLastCalledWith(['skipped', 'completed'])
    // Salt renders the remove affordance for pills while the field has focus.
    await user.click(screen.getByRole('combobox', { name: 'Filter by status' }))
    expect(
      screen.getByRole('button', { name: 'Remove Skipped' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Remove Implemented' }),
    ).toBeInTheDocument()
  })

  it('only narrows options while searching in search mode', async () => {
    const user = userEvent.setup()
    const onText = vi.fn()
    const onSelected = vi.fn()
    render(<Harness textMode="search" onText={onText} onSelected={onSelected} />)

    const input = screen.getByRole('combobox', { name: 'Filter by status' })
    await user.type(input, 'impl')

    expect(onText).not.toHaveBeenCalled()
    expect(screen.getByRole('option', { name: 'Implemented' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Ready' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('option', { name: 'Implemented' }))
    expect(onSelected).toHaveBeenLastCalledWith(['completed'])
    expect(input).toHaveValue('')
  })
})
