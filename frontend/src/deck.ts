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

/**
 * Whether this row is an accepted item that came back for review.
 *
 * That happens when the accepted deviation's submission failed: the item returns to
 * `needs_review` so the operator can correct it and retry. It belongs in the deck, but it
 * is not new work — see `orderDeckRows`.
 */
export function isReturnedRow(row: ItemRow): boolean {
  return row.status === 'needs_review' && row.decision?.decision === 'accept'
}

/** Whether one row belongs in the working deck. */
export function isDeckRow(row: ItemRow): boolean {
  if (!row.present || !DECIDABLE_STATUSES.has(row.status)) {
    return false
  }
  if (!row.decision) {
    return true
  }
  return isReturnedRow(row)
}

/**
 * Order the deck: pinned cards first, then undecided cards, then returned ones.
 *
 * `DeviationsPage` owns the pin state and calls this on every render; the helper is pure
 * and never fetches. Rows that are already gone from the deck, and repeated keys, are
 * ignored so a stale pin can neither duplicate a card nor invent one.
 *
 * An accepted item whose submission failed comes back for review, but it is not new work:
 * it queues behind every card the operator has not decided yet, so a failure cannot jump
 * ahead of the untouched queue. An explicit pin still brings it to the front, because
 * that is the operator saying "this one next".
 */
export function orderDeckRows(
  rows: readonly ItemRow[],
  pinnedKeys: readonly string[],
): ItemRow[] {
  const byKey = new Map(rows.map((row) => [row.key, row]))
  const pinned: ItemRow[] = []
  const seen = new Set<string>()
  for (const key of pinnedKeys) {
    const row = byKey.get(key)
    if (row === undefined || seen.has(key)) {
      continue
    }
    pinned.push(row)
    seen.add(key)
  }
  const rest = rows.filter((row) => !seen.has(row.key))
  return [
    ...pinned,
    ...rest.filter((row) => !isReturnedRow(row)),
    ...rest.filter((row) => isReturnedRow(row)),
  ]
}
