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

/**
 * Reorder the deck so pinned rows come first, in the order they were checked.
 *
 * `DeviationsPage` owns the pin state and calls this on every render; the helper is pure
 * and never fetches. Rows that are already gone from the deck, and repeated keys, are
 * ignored so a stale pin can neither duplicate a card nor invent one. Rows that are not
 * pinned keep their incoming (server `last_seen`) order.
 */
export function orderDeckRows(
  rows: readonly ItemRow[],
  pinnedKeys: readonly string[],
): ItemRow[] {
  if (pinnedKeys.length === 0) {
    return [...rows]
  }
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
  return [...pinned, ...rows.filter((row) => !seen.has(row.key))]
}
