/**
 * Status pill. The label is always rendered; tone is only a visual hint (FR-9.10).
 */

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
