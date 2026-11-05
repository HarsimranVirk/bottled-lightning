/**
 * The deck's accept-and-submit sequence, kept pure so the ordering and rollback are
 * testable without rendering the page.
 */

import type { DecisionKind } from './api'
import { hasChanges } from './format'

export interface AcceptanceActions {
  /** Persist the card's cleaned values. */
  patch: (changes: Record<string, string | null>) => Promise<unknown>
  /** Record the accept or skip decision. */
  decide: (decision: DecisionKind) => Promise<unknown>
  /** Enqueue the single submit job. */
  submit: () => Promise<unknown>
  /** Revert the accept when the job cannot be queued. */
  undo: () => Promise<unknown>
}

/**
 * Apply one deck decision.
 *
 * Accept with at least one non-empty value is three ordered writes: patch, decision,
 * job. Accept with no values records the decision only. Skip records the decision only.
 * If the job cannot be queued, the just-recorded accept is undone so the card stays
 * actionable; the original job error is re-thrown.
 *
 * Returns whether a submit job was requested, for the caller's announcement.
 */
export async function acceptAndSubmit(
  decision: DecisionKind,
  values: Record<string, string | null>,
  actions: AcceptanceActions,
): Promise<boolean> {
  if (decision !== 'accept') {
    await actions.decide(decision)
    return false
  }

  const shouldSubmit = hasChanges(values)
  if (shouldSubmit) {
    await actions.patch(values)
  }
  await actions.decide(decision)
  if (!shouldSubmit) {
    return false
  }

  try {
    await actions.submit()
  } catch (error) {
    try {
      await actions.undo()
    } catch {
      // Keep the original job error; the caller surfaces it.
    }
    throw error
  }
  return true
}
