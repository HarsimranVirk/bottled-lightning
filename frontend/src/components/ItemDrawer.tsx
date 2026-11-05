/**
 * Item detail panel: values grouped by target object, read-only attributes, the five
 * object links, the review decision, and history. Built from Salt surfaces only.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  Divider,
  FlexLayout,
  GridLayout,
  H2,
  Link,
  Panel,
  StackLayout,
  Text,
} from '@salt-ds/core'

import type { ItemDetail, PageRefView, WorkflowFieldView } from '../api'
import { displayValue, fieldValue, formatTime } from '../format'
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
    <Panel className="drawer" aria-label={`Item ${detail.key}`}>
      <FlexLayout justify="space-between" align="start" gap={2}>
        <StackLayout gap={0.5}>
          <H2>{detail.key}</H2>
          <FlexLayout gap={1} align="center" wrap>
            <StatusChip status={detail.status} labels={terminalLabels} />
            {detail.approvedAt ? (
              <Text color="secondary" styleAs="label">
                Approved {detail.approvedAt}
              </Text>
            ) : null}
            {detail.recordUrl ? (
              <Link href={detail.recordUrl} target="_blank">
                Open in Salesforce
              </Link>
            ) : null}
          </FlexLayout>
        </StackLayout>
        <Button appearance="transparent" onClick={onClose}>
          Close
        </Button>
      </FlexLayout>

      {detail.decision ? (
        <FlexLayout gap={1} align="center" wrap>
          <DecisionChip decision={detail.decision.decision} />
          <Text styleAs="label">
            {detail.decision.decision === 'accept' ? 'Accepted' : 'Rejected'}{' '}
            {formatTime(detail.decision.at)}
            {detail.decision.reason ? ` — ${detail.decision.reason}` : ''}
          </Text>
          {onUndoDecision ? (
            <Button appearance="bordered" onClick={onUndoDecision} disabled={undoing}>
              Undo decision
            </Button>
          ) : null}
        </FlexLayout>
      ) : null}

      {detail.reason ? (
        <Banner status="error">
          <BannerContent>{detail.reason}</BannerContent>
        </Banner>
      ) : null}

      {[...grouped.entries()].map(([kind, group]) => (
        <StackLayout gap={1} key={kind}>
          <Text styleAs="h3">{kind.replace(/_/g, ' ')}</Text>
          <GridLayout columns={2} gap={1}>
            {group.map((field) => (
              <StackLayout gap={0} key={field.key}>
                <Text color="secondary" styleAs="label">
                  {field.label}
                </Text>
                <Text>{displayValue(field, fieldValue(detail.fields, field.key))}</Text>
              </StackLayout>
            ))}
          </GridLayout>
        </StackLayout>
      ))}

      <Divider />
      <StackLayout gap={1}>
        <Text styleAs="h3">Extracted attributes</Text>
        <GridLayout columns={2} gap={1}>
          {Object.entries(detail.attributes).map(([name, value]) => (
            <StackLayout gap={0} key={name}>
              <Text color="secondary" styleAs="label">
                {name.replace(/_/g, ' ')}
              </Text>
              <Text style={name === 'description' ? { whiteSpace: 'pre-wrap' } : undefined}>
                {value ?? '—'}
              </Text>
            </StackLayout>
          ))}
        </GridLayout>
      </StackLayout>

      <Divider />
      <StackLayout gap={1}>
        <Text styleAs="h3">Objects</Text>
        <StackLayout gap={0.5}>
          {refKinds.map((kind) => {
            const ref = refFor(detail, kind)
            return (
              <FlexLayout key={kind} gap={2} align="baseline">
                <Text color="secondary" styleAs="label">
                  {kind.replace(/_/g, ' ')}
                </Text>
                {ref ? (
                  <Link href={ref.url} target="_blank">
                    {ref.name}
                  </Link>
                ) : (
                  <Text color="secondary">not found</Text>
                )}
              </FlexLayout>
            )
          })}
        </StackLayout>
      </StackLayout>

      <Divider />
      <StackLayout gap={1}>
        <Text styleAs="h3">History</Text>
        {detail.decisions.length === 0 && detail.edits.length === 0 ? (
          <Text color="secondary">No edits or decisions recorded.</Text>
        ) : (
          <StackLayout gap={0.5}>
            {detail.decisions.map((decision, index) => (
              <Text key={`decision-${index}`} styleAs="label">
                {decision.decision === 'accept' ? 'accepted' : 'rejected'}
                {decision.reason ? ` — ${decision.reason}` : ''} · {formatTime(decision.at)}
              </Text>
            ))}
            {detail.edits.map((edit, index) => (
              <Text key={`${edit.field}-${index}`} styleAs="label">
                {edit.field}: {edit.oldValue ?? '—'} → {edit.newValue ?? '—'} ·{' '}
                {formatTime(edit.at)}
              </Text>
            ))}
          </StackLayout>
        )}
      </StackLayout>
    </Panel>
  )
}
