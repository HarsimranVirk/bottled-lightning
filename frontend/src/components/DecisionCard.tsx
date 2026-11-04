/**
 * One deviation as a review card: every editable value, the reason when the item needs
 * review, and a details link. The card is presentation only; the deck owns gestures and
 * decisions.
 */

import type { JSX } from 'react'
import { Button } from '@salt-ds/core'

import type { ItemRow, WorkflowFieldView } from '../api'
import { fieldValue } from '../format'
import { DecisionChip, StatusChip } from './StatusChip'

interface Props {
  row: ItemRow
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  /** 0 is the top card, 1-2 are the peeks behind it. */
  offset: number
  onDetails: () => void
}

export function DecisionCard({ row, fields, terminalLabels, offset, onDetails }: Props): JSX.Element {
  const missing = fields.filter((field) => fieldValue(row.fields, field.key) === '—').length

  return (
    <article
      className="decision-card"
      data-offset={offset}
      aria-roledescription="review card"
      aria-label={row.key}
      data-testid={offset === 0 ? 'top-card' : undefined}
    >
      <header className="card-head">
        <span className="mono card-key">{row.key}</span>
        <StatusChip status={row.status} labels={terminalLabels} />
      </header>

      <div className="card-meta">
        <span>{row.approvedAt ? `Approved ${row.approvedAt}` : 'No approval date'}</span>
        {row.decision ? <DecisionChip decision={row.decision.decision} /> : null}
      </div>

      {row.reason ? <p className="reason">{row.reason}</p> : null}

      <dl className="card-values">
        {fields.map((field) => (
          <div key={field.key} className="card-value">
            <dt>{field.label}</dt>
            <dd className={field.valueType === 'text' ? '' : 'mono'}>
              {fieldValue(row.fields, field.key)}
            </dd>
          </div>
        ))}
      </dl>

      {missing > 0 ? (
        <p className="card-warning">
          {missing} {missing === 1 ? 'value is' : 'values are'} missing — check the description
          before accepting.
        </p>
      ) : null}

      <footer className="card-foot">
        <span className="muted card-hint">← reject · → accept · U undo</span>
        <Button appearance="transparent" onClick={onDetails}>
          Details
        </Button>
      </footer>
    </article>
  )
}
