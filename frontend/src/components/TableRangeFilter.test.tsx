/** Range filter: both bounds stay native inputs inside one labelled group (FR-9.21). */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TableRangeFilter } from './TableRangeFilter'

describe('TableRangeFilter', () => {
  it('renders the two bounds as one range group', () => {
    const { container } = render(
      <TableRangeFilter
        fromLabel="Decided from"
        toLabel="Decided to"
        from=""
        to=""
        onFrom={vi.fn()}
        onTo={vi.fn()}
        type="date"
      />,
    )
    expect(screen.getByLabelText('Decided from')).toHaveAttribute('type', 'date')
    expect(screen.getByLabelText('Decided to')).toHaveAttribute('type', 'date')
    expect(container.querySelectorAll('.range-filter')).toHaveLength(1)
  })

  it('reports each bound separately', async () => {
    const user = userEvent.setup()
    const onFrom = vi.fn()
    const onTo = vi.fn()
    render(
      <TableRangeFilter
        fromLabel="Duration from"
        toLabel="Duration to"
        from=""
        to=""
        onFrom={onFrom}
        onTo={onTo}
        type="number"
      />,
    )

    await user.type(screen.getByLabelText('Duration from'), '1')
    await user.type(screen.getByLabelText('Duration to'), '2')

    expect(onFrom).toHaveBeenLastCalledWith('1')
    expect(onTo).toHaveBeenLastCalledWith('2')
  })
})
