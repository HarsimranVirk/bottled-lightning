/** Deck membership: present, decidable, and the failed-accepted exception. */

import { describe, expect, it } from 'vitest'

import type { DecisionView, ItemRow } from './api'
import { isDeckRow } from './deck'

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
})
