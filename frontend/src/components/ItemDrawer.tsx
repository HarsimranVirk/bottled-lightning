/**
 * Item detail panel: values grouped by target object, read-only attributes, the five
 * object links, the review decision, and history.
 */

import type { JSX } from 'react'
import { Button, Divider, H2, H3, Link, Text } from '@salt-ds/core'

import type { ItemDetail, PageRefView, WorkflowFieldView } from '../api'
import { fieldValue, formatTime } from '../format'
import { DecisionChip, StatusChip } from './StatusChip'

interface Props {
  detail: ItemDetail
  fields: WorkflowFieldView[]
  refKinds: string[]
  terminalLabels: Record<string, string>
  onClose: () => void
  /** Present when a decision exists and the item is still decidable. */
  onUndoDecision?: () => void
  undoing?: boolean
}

function groups(fields: WorkflowFieldView[]): Map<string, WorkflowFieldView[]> {
  const map = new Map<string, WorkflowFieldView[]>()
  for (const field of fields) {
    const kind = field.targets[0] ?? 'other'
    const list = map.get(kind) ?? []
    list.push(field)
    map.set(kind, list)
  }
  return map
}

function refFor(detail: ItemDetail, kind: string): PageRefView | undefined {
  return detail.refs.find((ref) => ref.kind === kind)
}

export function ItemDrawer({
  detail,
  fields,
  refKinds,
  terminalLabels,
  onClose,
  onUndoDecision,
  undoing = false,
}: Props): JSX.Element {
  const grouped = groups(fields)
  return (
    <aside className="drawer" aria-label={`Item ${detail.key}`}>
      <div className="drawer-head">
        <div>
          <H2>{detail.key}</H2>
          <div className="drawer-meta">
            <StatusChip status={detail.status} labels={terminalLabels} />
            {detail.approvedAt ? <Text>Approved {detail.approvedAt}</Text> : null}
            {detail.recordUrl ? <Link href={detail.recordUrl} target="_blank">Open in Salesforce</Link> : null}
          </div>
        </div>
        <Button appearance="transparent" onClick={onClose}>Close</Button>
      </div>

      {detail.decision ? (
        <div className="decision-banner">
          <DecisionChip decision={detail.decision.decision} />
          <Text>
            {detail.decision.decision === 'accept' ? 'Accepted' : 'Rejected'} {formatTime(detail.decision.at)}
            {detail.decision.reason ? ` — ${detail.decision.reason}` : ''}
          </Text>
          {onUndoDecision ? (
            <Button appearance="bordered" onClick={onUndoDecision} disabled={undoing}>
              Undo decision
            </Button>
          ) : null}
        </div>
      ) : null}

      {detail.reason ? <Text className="reason">{detail.reason}</Text> : null}

      {[...grouped.entries()].map(([kind, group]) => (
        <section key={kind}>
          <H3>{kind.replace(/_/g, ' ')}</H3>
          <dl className="fields">
            {group.map((field) => (
              <div key={field.key} className="field">
                <dt>{field.label}</dt>
                <dd className="mono">{fieldValue(detail.fields, field.key)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}

      <Divider />
      <section>
        <H3>Extracted attributes</H3>
        <dl className="fields">
          {Object.entries(detail.attributes).map(([name, value]) => (
            <div key={name} className="field">
              <dt>{name.replace(/_/g, ' ')}</dt>
              <dd className={name === 'description' ? 'description' : 'mono'}>{value ?? '—'}</dd>
            </div>
          ))}
        </dl>
      </section>

      <Divider />
      <section>
        <H3>Objects</H3>
        <ul className="refs">
          {refKinds.map((kind) => {
            const ref = refFor(detail, kind)
            return (
              <li key={kind}>
                <span className="mono">{kind}</span>
                {ref ? (
                  <Link href={ref.url} target="_blank">{ref.name}</Link>
                ) : (
                  <span className="missing">not found</span>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <Divider />
      <section>
        <H3>History</H3>
        {detail.decisions.length === 0 && detail.edits.length === 0 ? (
          <Text color="secondary">No edits or decisions recorded.</Text>
        ) : (
          <ul className="history">
            {detail.decisions.map((decision, index) => (
              <li key={`decision-${index}`}>
                <span className="mono">decision</span>{' '}
                {decision.decision === 'accept' ? 'accepted' : 'rejected'}
                {decision.reason ? ` — ${decision.reason}` : ''}{' '}
                <span className="muted">{formatTime(decision.at)}</span>
              </li>
            ))}
            {detail.edits.map((edit, index) => (
              <li key={`${edit.field}-${index}`}>
                <span className="mono">{edit.field}</span> {edit.oldValue ?? '—'} → {edit.newValue ?? '—'}{' '}
                <span className="muted">{formatTime(edit.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  )
}
