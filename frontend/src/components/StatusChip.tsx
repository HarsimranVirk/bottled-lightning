/**
 * Status pill. The label is always rendered; tone is only a visual hint (FR-9.10).
 */

import type { DecisionKind } from '../api'
import { statusLabel, statusTone } from '../format'

interface Props {
  status: string
  labels?: Record<string, string>
}

export function StatusChip({ status, labels }: Props): React.JSX.Element {
  return (
    <span className="chip" data-tone={statusTone(status)}>
      {statusLabel(status, labels)}
    </span>
  )
}

/** Review decision pill; the word carries the meaning, tone is decoration. */
export function DecisionChip({ decision }: { decision: DecisionKind }): React.JSX.Element {
  return (
    <span className="chip" data-tone={decision === 'accept' ? 'success' : 'danger'}>
      {decision === 'accept' ? 'Accepted' : 'Rejected'}
    </span>
  )
}
