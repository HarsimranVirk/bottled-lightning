/**
 * Which items belong in the working review deck.
 *
 * Presence is part of the rule: an item that has left the Salesforce list must never
 * keep a card while its backend closure is pending. The one exception is a failed
 * accepted item in needs_review, which returns so the operator can correct and retry.
 */

import type { ItemRow } from './api'

/** Statuses the deck lets the operator act on (FR-10.5). */
export const DECIDABLE_STATUSES: ReadonlySet<string> = new Set([
  'ready',
  'editing',
  'needs_review',
])

/** Whether one row belongs in the working deck. */
export function isDeckRow(row: ItemRow): boolean {
  if (!row.present || !DECIDABLE_STATUSES.has(row.status)) {
    return false
  }
  if (!row.decision) {
    return true
  }
  return row.status === 'needs_review' && row.decision.decision === 'accept'
}
