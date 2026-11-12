/** Deck membership: present, decidable, and the failed-accepted exception. */

import { describe, expect, it } from 'vitest'

import type { DecisionView, ItemRow } from './api'
import { isDeckRow, isReturnedRow, orderDeckRows } from './deck'

function row(overrides: Partial<ItemRow> = {}): ItemRow {
  return {
    epoch: 1,
    fields: {},
    key: 'Deviation-03112026-486382',
    present: true,
    status: 'ready',
    ...overrides,
  }
}

function decision(value: string): DecisionView {
  return { at: '2026-11-05T09:00:00Z', decision: value }
}

describe('isDeckRow', () => {
  it('shows a present, undecided, decidable item', () => {
    expect(isDeckRow(row())).toBe(true)
  })

  it('never shows an item that left the Salesforce list', () => {
    expect(isDeckRow(row({ present: false }))).toBe(false)
    expect(isDeckRow(row({ present: false, status: 'needs_review' }))).toBe(false)
  })

  it('shows a failed accepted item again for recovery', () => {
    expect(
      isDeckRow(
        row({ status: 'needs_review', decision: decision('accept') }),
      ),
    ).toBe(true)
  })

  it('keeps decided items out otherwise', () => {
    expect(isDeckRow(row({ decision: decision('accept') }))).toBe(false)
    expect(isDeckRow(row({ decision: decision('reject') }))).toBe(false)
  })

  it('hides in-flight and terminal statuses', () => {
    for (const status of ['submitting', 'applying', 'completed', 'closed']) {
      expect(isDeckRow(row({ status }))).toBe(false)
    }
  })

  it('recognises only an accepted item in needs_review as returned', () => {
    expect(
      isReturnedRow(row({ status: 'needs_review', decision: decision('accept') })),
    ).toBe(true)
    expect(isReturnedRow(row({ status: 'needs_review' }))).toBe(false)
    expect(isReturnedRow(row({ status: 'ready', decision: decision('accept') }))).toBe(false)
  })
})

describe('orderDeckRows', () => {
  const first = row({ key: 'Deviation-1-1' })
  const second = row({ key: 'Deviation-2-2' })
  const third = row({ key: 'Deviation-3-3' })

  it('keeps the incoming order when nothing is pinned', () => {
    expect(orderDeckRows([first, second, third], []).map((item) => item.key)).toEqual([
      'Deviation-1-1',
      'Deviation-2-2',
      'Deviation-3-3',
    ])
  })

  it('moves one pinned row to the front', () => {
    expect(orderDeckRows([first, second, third], ['Deviation-2-2']).map((item) => item.key)).toEqual([
      'Deviation-2-2',
      'Deviation-1-1',
      'Deviation-3-3',
    ])
  })

  it('keeps several pins in check order', () => {
    expect(
      orderDeckRows([first, second, third], ['Deviation-3-3', 'Deviation-1-1']).map(
        (item) => item.key,
      ),
    ).toEqual(['Deviation-3-3', 'Deviation-1-1', 'Deviation-2-2'])
  })

  it('ignores keys that are not in the current deck', () => {
    expect(orderDeckRows([first, second], ['Deviation-9-9']).map((item) => item.key)).toEqual([
      'Deviation-1-1',
      'Deviation-2-2',
    ])
  })

  it('queues a returned card behind every undecided card', () => {
    const returned = row({
      key: 'Deviation-0-0',
      status: 'needs_review',
      decision: decision('accept'),
    })
    expect(orderDeckRows([returned, first, second], []).map((item) => item.key)).toEqual([
      'Deviation-1-1',
      'Deviation-2-2',
      'Deviation-0-0',
    ])
  })

  it('keeps returned cards in their incoming order', () => {
    const one = row({ key: 'Deviation-0-1', status: 'needs_review', decision: decision('accept') })
    const two = row({ key: 'Deviation-0-2', status: 'needs_review', decision: decision('accept') })
    expect(orderDeckRows([one, two, first], []).map((item) => item.key)).toEqual([
      'Deviation-1-1',
      'Deviation-0-1',
      'Deviation-0-2',
    ])
  })

  it('lets an explicit pin bring a returned card to the front', () => {
    const returned = row({
      key: 'Deviation-0-0',
      status: 'needs_review',
      decision: decision('accept'),
    })
    expect(
      orderDeckRows([returned, first], ['Deviation-0-0']).map((item) => item.key),
    ).toEqual(['Deviation-0-0', 'Deviation-1-1'])
  })

  it('ignores duplicate pins and never duplicates a card', () => {
    expect(
      orderDeckRows([first, second], ['Deviation-2-2', 'Deviation-2-2']).map(
        (item) => item.key,
      ),
    ).toEqual(['Deviation-2-2', 'Deviation-1-1'])
  })
})
