/** The unified view: one compact row per item. Read-only in Slice A. */

import type { JSX } from 'react'
import { StatusChip } from './StatusChip'
import type { ItemRow, WorkflowFieldView } from '../api'

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  onOpen: (key: string) => void
}

function value(row: ItemRow, key: string): string {
  const field = row.fields[key]
  if (!field) return '—'
  return field.proposed ?? field.extracted ?? field.applied ?? '—'
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
                {value(row, field.key)}
              </td>
            ))}
            <td>{row.approvedAt ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
