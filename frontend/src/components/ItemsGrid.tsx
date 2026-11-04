/** The list view: one compact row per item, with its review decision. Read-only. */

import type { JSX } from 'react'

import type { ItemRow, WorkflowFieldView } from '../api'
import { fieldValue } from '../format'
import { DecisionChip, StatusChip } from './StatusChip'

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  onOpen: (key: string) => void
}

export function ItemsGrid({ rows, fields, terminalLabels, onOpen }: Props): JSX.Element {
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Status</th>
          <th>Deviation</th>
          {fields.map((field) => (
            <th key={field.key} className={field.valueType === 'text' ? '' : 'num'}>
              {field.label}
            </th>
          ))}
          <th>Decision</th>
          <th>Approved</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.key}
            tabIndex={0}
            onClick={() => onOpen(row.key)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onOpen(row.key)
              }
            }}
          >
            <td>
              <StatusChip status={row.status} labels={terminalLabels} />
            </td>
            <td className="mono">{row.key}</td>
            {fields.map((field) => (
              <td key={field.key} className={field.valueType === 'text' ? '' : 'num mono'}>
                {fieldValue(row.fields, field.key)}
              </td>
            ))}
            <td>{row.decision ? <DecisionChip decision={row.decision.decision} /> : '—'}</td>
            <td>{row.approvedAt ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
